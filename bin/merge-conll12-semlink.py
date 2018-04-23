from __future__ import print_function


conll12_fname = "~/research/data/conll-2012-new/conll2012-train.txt"
semlink_fname = "~/research/data/semlink-1.2.2c/semlink-wsj.txt"

semlink_map = {}
with open(semlink_fname, 'r') as semlink_file:
  for line in semlink_file:
    line = line.strip()
    if line:
      split_line = line.split()

      # key is doc name without ending
      key = (split_line[0].split('.')[0], split_line[1])
      value = (split_line[7], ' '.join(split_line[10:]))
      if key not in semlink_map:
        semlink_map[key] = []
      semlink_map[key].append(value)
print(semlink_map)

with open(conll12_fname, 'r') as conll12_file:
  # want to scan conll12 file until we find a sentence that is in semlink,
  # then process that sentence
  for line in conll12_file:
    line = line.strip()
    if line:
      split_line = line.split()