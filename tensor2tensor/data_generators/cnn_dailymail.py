# coding=utf-8
# Copyright 2017 The Tensor2Tensor Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Data generators for the CNN and Daily Mail datasets."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import os
import tarfile
import hashlib

# Dependency imports

import six
from tensor2tensor.data_generators import generator_utils
from tensor2tensor.data_generators import problem
from tensor2tensor.data_generators import text_encoder
from tensor2tensor.utils import registry

import tensorflow as tf


# Links to data from http://cs.nyu.edu/~kcho/DMQA/
_CNN_STORIES_DRIVE_URL = "https://drive.google.com/uc?export=download&id=0BwmD_VLjROrfTHk4NFg2SndKcjQ"

_DAILYMAIL_STORIES_DRIVE_URL = "https://drive.google.com/uc?export=download&id=0BwmD_VLjROrfM1BxdkxVaTY2bWs"

# Note: using See et al. (2017) as reference for data generation
# For more info, use the links below

# Train/Dev/Test Splits for summarization data
_TRAIN_URLS = "https://raw.githubusercontent.com/abisee/cnn-dailymail/master/url_lists/all_train.txt"
_DEV_URLS = "https://raw.githubusercontent.com/abisee/cnn-dailymail/master/url_lists/all_val.txt"
_TEST_URLS = "https://github.com/abisee/cnn-dailymail/blob/master/url_lists/all_test.txt"

# End-of-sentence marker.
EOS = text_encoder.EOS_ID

# Techniques for data prep from See et al. (2017)
dm_single_close_quote = u'\u2019' # unicode
dm_double_close_quote = u'\u201d'
END_TOKENS = [u'.', u'!', u'?', u'...', u"'", u"`", u'"', dm_single_close_quote, dm_double_close_quote, u")"] # acceptable ways to end a sentence


def _maybe_download_corpora(tmp_dir, is_training):
  """Download corpora if necessary and unzip them.

  Args:
    tmp_dir: directory containing dataset.

  Returns:
    list of all files generated and path to file containing train/dev/test split info.
  """
  cnn_filename = "cnn_stories.tgz"
  cnn_finalpath = os.path.join(tmp_dir, "cnn/stories/")
  dailymail_filename = "dailymail_stories.tgz"
  dailymail_finalpath = os.path.join(tmp_dir, "dailymail/stories/")
  if not tf.gfile.Exists(cnn_finalpath):
    cnn_file = generator_utils.maybe_download_from_drive(
        tmp_dir, cnn_filename, _CNN_STORIES_DRIVE_URL)
    with tarfile.open(cnn_file, "r:gz") as cnn_tar:
      cnn_tar.extractall(tmp_dir)
  if not tf.gfile.Exists(dailymail_finalpath):
    dailymail_file = generator_utils.maybe_download_from_drive(
        tmp_dir, dailymail_filename, _DAILYMAIL_STORIES_DRIVE_URL)
    with tarfile.open(dailymail_file, "r:gz") as dailymail_tar:
      dailymail_tar.extractall(tmp_dir)

  cnn_files = tf.gfile.Glob(cnn_finalpath + "*")
  dailymail_files = tf.gfile.Glob(dailymail_finalpath + "*")
  all_files = cnn_files + dailymail_files

  if is_training:
    urls_path = generator_utils.maybe_download(tmp_dir, "all_train.txt", _TRAIN_URLS)
  else:
    urls_path = generator_utils.maybe_download(tmp_dir, "all_val.txt", _DEV_URLS)

  return all_files, urls_path

def example_splits(url_file, all_files):
  def generate_hash(inp):
      """Generate a sha1 hash to match the raw url to the filename extracted"""
      h = hashlib.sha1()
      h.update(inp)
      return h.hexdigest()

  all_files_map = {f.split("/")[-1]:f for f in all_files}

  urls = []
  for line in tf.gfile.Open(url_file):
    urls.append(line.strip())

  filelist = []
  for url in urls:
      url_hash = generate_hash(url)
      filename = url_hash + ".story"
      if filename not in all_files_map:
        tf.logging.info("Missing file: %s" % url)
        continue
      filelist.append(all_files_map[filename])

  tf.logging.info("Found %d examples" % len(filelist))

  return filelist

def example_generator(tmp_dir, is_training):
  def fix_run_on_sents(line):
    if u"@highlight" in line: return line
    if line=="": return line
    if line[-1] in END_TOKENS: return line
    return line + u"."

  all_files, urls_path = _maybe_download_corpora(tmp_dir, is_training)
  filelist = example_splits(urls_path, all_files)

  for story_file in filelist:
    story = []
    summary = []
    reading_highlights = False
    for line in tf.gfile.Open(story_file):
      line = unicode(line.strip(), "utf-8") if six.PY2 else line.strip().decode("utf-8")
      line = fix_run_on_sents(line)
      if line == "":
          continue
      elif line.startswith(u"@highlight"):
          if len(story) == 0: break # No article text
          reading_highlights = True
      elif reading_highlights:
          summary.append(line)
      else:
          story.append(line)
    yield " ".join(story) + u" <summary> " + " ".join(summary)


def _story_summary_split(story):
  split_str = u" <summary> "
  split_str_len = len(split_str)
  split_pos = story.find(split_str)
  return story[:split_pos], story[split_pos+split_str_len:] # story, summary


@registry.register_problem
class SummarizeCnnDailymail32k(problem.Text2TextProblem):
  """Summarize CNN and Daily Mail articles to their summary highlights."""

  @property
  def is_character_level(self):
    return False

  @property
  def has_inputs(self):
    return True

  @property
  def input_space_id(self):
    return problem.SpaceID.EN_TOK

  @property
  def target_space_id(self):
    return problem.SpaceID.EN_TOK

  @property
  def num_shards(self):
    return 100

  @property
  def vocab_name(self):
    return "vocab.cnndailymail"

  @property
  def use_subword_tokenizer(self):
    return True

  @property
  def targeted_vocab_size(self):
    return 2**15  # 32768

  @property
  def use_train_shards_for_dev(self):
    return False

  def generator(self, data_dir, tmp_dir, is_training):
    encoder = generator_utils.get_or_generate_vocab_inner(
        data_dir, self.vocab_file, self.targeted_vocab_size,
        example_generator(tmp_dir, is_training))
    for example in example_generator(tmp_dir, is_training):
      story, summary = _story_summary_split(example)
      encoded_summary = encoder.encode(summary) + [EOS]
      encoded_story = encoder.encode(story) + [EOS]
      yield {"inputs": encoded_story, "targets": encoded_summary}
