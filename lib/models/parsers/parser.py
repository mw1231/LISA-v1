#!/usr/bin/env python
# -*- coding: UTF-8 -*-
 
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import numpy as np
import time
import tensorflow as tf

from lib.models import nn

from vocab import Vocab
from lib.models.parsers.base_parser import BaseParser

#***************************************************************
class Parser(BaseParser):
  """"""
  
  #=============================================================
  def __call__(self, dataset, moving_params=None):
    """"""
    
    vocabs = dataset.vocabs
    inputs = dataset.inputs
    targets = dataset.targets
    
    reuse = (moving_params is not None)
    self.tokens_to_keep3D = tf.expand_dims(tf.to_float(tf.greater(inputs[:,:,0], vocabs[0].ROOT)), 2)
    self.sequence_lengths = tf.reshape(tf.reduce_sum(self.tokens_to_keep3D, [1, 2]), [-1,1])
    self.n_tokens = tf.reduce_sum(self.sequence_lengths)
    self.moving_params = moving_params
    
    word_inputs, pret_inputs = vocabs[0].embedding_lookup(inputs[:,:,0], inputs[:,:,1], moving_params=self.moving_params)
    tag_inputs = vocabs[1].embedding_lookup(inputs[:,:,2], moving_params=self.moving_params)
    if self.add_to_pretrained:
      word_inputs += pret_inputs
    if self.word_l2_reg > 0:
      unk_mask = tf.expand_dims(tf.to_float(tf.greater(inputs[:,:,1], vocabs[0].UNK)),2)
      word_loss = self.word_l2_reg*tf.nn.l2_loss((word_inputs - pret_inputs) * unk_mask)
    embed_inputs = self.embed_concat(word_inputs, tag_inputs)
    
    top_recur = embed_inputs

    kernel = 3
    # cnn_dim = 768
    # cnn_layers = 2
    # num_heads = 4
    # head_size = 128
    hidden_size = self.num_heads * self.head_size
    attn_dropout = 0.67
    prepost_dropout = 0.67
    relu_dropout = 0.67
    # relu_hidden_size = 512
    print("num heads: ", self.num_heads)
    print("cnn dim: ", self.cnn_dim)
    print("relu hidden size: ", self.relu_hidden_size)

    # if moving_params is not None:
    #   attn_dropout = 1.0
    #   prepost_dropout = 1.0
    #   relu_dropout = 1.0
    #   self.recur_keep_prob = 1.0

    for i in xrange(self.cnn_layers):
      with tf.variable_scope('CNN%d' % i, reuse=reuse):
        top_recur = self.CNN(top_recur, 1, kernel, self.cnn_dim,
                             self.recur_keep_prob if i < self.n_recur - 1 else 1.0,
                             self.info_func if i < self.n_recur - 1 else tf.identity)

    with tf.variable_scope('proj', reuse=reuse):
      top_recur = tf.expand_dims(top_recur, 1)
      params = tf.get_variable("proj", [1, 1, self.cnn_dim, hidden_size])
      top_recur = tf.nn.conv2d(top_recur, params, [1, 1, 1, 1], "SAME")
      top_recur = tf.squeeze(top_recur, 1)

    with tf.variable_scope('2d', reuse=reuse):
      input_shape = tf.shape(embed_inputs)
      # batch_size = input_shape[0]
      bucket_size = input_shape[1]
      top_recur_rows, top_recur_cols = tf.split(top_recur, num_or_size_splits=2, axis=-1)
      top_recur_rows = tf.tile(tf.expand_dims(top_recur_rows, 1), [1, bucket_size, 1, 1])
      top_recur_cols = tf.tile(tf.expand_dims(top_recur_cols, 2), [1, 1, bucket_size, 1])
      top_recur_2d = tf.concat([top_recur_cols, top_recur_rows], axis=-1)
      for i in xrange(4): # todo pass this in
        with tf.variable_scope('CNN%d' % i, reuse=reuse):
          top_recur_2d = self.CNN(top_recur_2d, kernel, kernel, 128, # todo pass this in
                               self.recur_keep_prob if i < self.n_recur - 1 else 1.0,
                               self.info_func if i < self.n_recur - 1 else tf.identity)

    #### TRANSFORMER ####
    # top_recur = nn.add_timing_signal_1d(top_recur)
    # attn_weights_by_layer = {}
    #
    # for i in xrange(self.n_recur):
    #   # RNN:
    #   # with tf.variable_scope('RNN%d' % i, reuse=reuse):
    #   #   top_recur, _ = self.RNN(top_recur)
    #
    #   # Transformer:
    #   with tf.variable_scope('Transformer%d' % i, reuse=reuse):
    #     top_recur, attn_weights = self.transformer(top_recur, hidden_size, self.num_heads,
    #                                  attn_dropout, relu_dropout, prepost_dropout, self.relu_hidden_size,
    #                                  self.info_func, reuse)
    #     attn_weights_by_layer[tf.get_variable_scope().name] = attn_weights
    # # if normalization is done in layer_preprocess, then it shuold also be done
    # # on the output, since the output can grow very large, being the sum of
    # # a whole stack of unnormalized layer outputs.
    #
    # top_recur = nn.layer_norm(top_recur, reuse)

    ##### HEADS / DEPS MLP #####
    # with tf.variable_scope('MLP', reuse=reuse):
    #   dep_mlp, head_mlp = self.MLP(top_recur, self.class_mlp_size+self.attn_mlp_size, n_splits=2)
    #   dep_arc_mlp, dep_rel_mlp = dep_mlp[:,:,:self.attn_mlp_size], dep_mlp[:,:,self.attn_mlp_size:]
    #   head_arc_mlp, head_rel_mlp = head_mlp[:,:,:self.attn_mlp_size], head_mlp[:,:,self.attn_mlp_size:]
      dep_rel_mlp, head_rel_mlp = self.MLP(top_recur_2d, 128, n_splits=2) # todo don't hardcode this


    with tf.variable_scope('Arcs', reuse=reuse):

      #### OLD ####
      # gate = self.gate(top_recur, hidden_size, hidden_size)
      # arc_logits = self.bilinear_classifier(dep_arc_mlp, head_arc_mlp)
      # # arc_logits_gated = tf.add(arc_logits, gate)
      # arc_output = self.output(arc_logits, targets[:,:,1])
      # # arc_output = self.output_svd(arc_logits_gated, targets[:,:,1])
      # gate_output = self.output_gate(gate, targets[:,:,1])

      arc_logits = self.MLP(top_recur_2d, 1, n_splits=1)

      arc_output = self.output2d(arc_logits, targets[:, :, 1])


      # 'probabilities': tf.reshape(probabilities2D, original_shape),
      # 'predictions': tf.reshape(predictions1D, flat_shape),
      # original_shape = tf.shape(arc_logits)
      # batch_size = original_shape[0]
      # bucket_size = original_shape[1]
      # flat_shape = tf.stack([batch_size, bucket_size])
      # probabilities = arc_output['probabilities']
      # predictions = tf.argmax(tf.reshape(probabilities, flat_shape))
      # probs2D = tf.reshape(probabilities, tf.stack([batch_size * bucket_size, -1]))
      # predictions = tf.reshape(tf.to_int32(tf.argmax(probs2D, 1)), flat_shape)

      if moving_params is None:
        predictions = targets[:,:,1]
      else:
        predictions = arc_output['predictions']

      predictions = tf.Print(predictions, [tf.shape(predictions)], summarize=10)
    with tf.variable_scope('MLP', reuse=reuse):
        flat_labels = tf.reshape(predictions, [-1])
        original_shape = tf.shape(arc_logits)
        batch_size = original_shape[0]
        bucket_size = original_shape[1]
        num_classes = len(vocabs[2])
        i1, i2, i3 = tf.meshgrid(tf.range(batch_size), tf.range(bucket_size), tf.range(bucket_size), indexing="ij")
        targ = i1 * bucket_size * bucket_size * num_classes + i2 * bucket_size * num_classes + i3 * num_classes + flat_labels
        idx = tf.reshape(targ, [-1])
        conditioned = tf.gather(tf.reshape(top_recur_2d, [-1, 128]), idx) # todo dont hardcode
        conditioned = tf.reshape(conditioned, [batch_size, bucket_size, 128])
        dep_rel_mlp, head_rel_mlp = self.MLP(conditioned, self.class_mlp_size+self.attn_mlp_size, n_splits=2)

    with tf.variable_scope('Rels', reuse=reuse):
      rel_logits, rel_logits_cond = self.conditional_bilinear_classifier(dep_rel_mlp, head_rel_mlp, len(vocabs[2]), predictions)
      rel_output = self.output(rel_logits, targets[:,:,2])
      rel_output['probabilities'] = self.conditional_probabilities(rel_logits_cond)
    
    output = {}
    output['probabilities'] = tf.tuple([arc_output['probabilities'],
                                        rel_output['probabilities']])
    output['predictions'] = tf.stack([arc_output['predictions'],
                                     rel_output['predictions']])
    output['correct'] = arc_output['correct'] * rel_output['correct']
    output['tokens'] = arc_output['tokens']
    output['n_correct'] = tf.reduce_sum(output['correct'])
    output['n_tokens'] = self.n_tokens
    output['accuracy'] = output['n_correct'] / output['n_tokens']
    output['loss'] = arc_output['loss'] + rel_output['loss']
    if self.word_l2_reg > 0:
      output['loss'] += word_loss
    
    output['embed'] = embed_inputs
    output['recur'] = top_recur
    # output['dep_arc'] = dep_arc_mlp
    # output['head_dep'] = head_arc_mlp
    # output['dep_rel'] = dep_rel_mlp
    # output['head_rel'] = head_rel_mlp
    output['arc_logits'] = arc_logits
    output['rel_logits'] = rel_logits

    output['rel_loss'] = rel_output['loss']
    output['log_loss'] = arc_output['loss'] #arc_output['log_loss']

    # output['2cycle_loss'] = arc_output['2cycle_loss']
    # output['roots_loss'] = arc_output['roots_loss']
    # output['svd_loss'] = arc_output['svd_loss']
    # output['2cycle_loss'] = gate_output['2cycle_loss']
    # output['roots_loss'] = gate_output['roots_loss']
    # output['svd_loss'] = gate_output['svd_loss']

    # output['attn_weights'] = attn_weights_by_layer
    return output
  
  #=============================================================
  def prob_argmax(self, parse_probs, rel_probs, tokens_to_keep):
    """"""
    start_time = time.time()
    parse_preds, roots_lt, roots_gt, cycles_2, cycles_n = self.parse_argmax(parse_probs, tokens_to_keep)
    rel_probs = rel_probs[np.arange(len(parse_preds)), parse_preds]
    rel_preds = self.rel_argmax(rel_probs, tokens_to_keep)
    total_time = time.time() - start_time
    return parse_preds, rel_preds, total_time, roots_lt, roots_gt, cycles_2, cycles_n
