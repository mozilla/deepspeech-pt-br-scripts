import pandas
import subprocess

from collections import Counter

# For a dataset where some transcripts repeat more than `limit` times, create a
# new dataset where a sentence only repeats at most `limit` times.
def limit_repeated_samples(df, limit):
    counter = Counter(df['transcript'].values)

    # No sentence repeats more than `limit` times, short-circuit
    if counter.most_common(1)[0][1] <= limit:
        return df

    # Collect samples with transcripts that repeat <= `limit` times in the dataset.
    idx_le_limit = df['transcript'].apply(lambda x: counter[x] <= limit)
    data_le_limit = df[idx_le_limit]
    data_gt_limit = df[~idx_le_limit]

    # Sentences that repeat > `limit` times in the dataset.
    sentences_gt_limit = [s for s, count in counter.most_common() if count > limit]

    # For each of those sentences, sample `limit` of them to add to new dataset
    sentence_samples = []
    for sentence in sentences_gt_limit:
        sentence_samples.append(df[df['transcript'] == sentence].sample(limit))

    new_df = pandas.concat([data_le_limit, *sentence_samples])

    new_counter = Counter(new_df['transcript'].values)
    assert new_counter.most_common(1)[0][1] <= limit

    return new_df


# From a dataset `df`, generate a dev set of size `dev_size` and a test set of
# size `test_size` using only sentences that appear once in the dataset. The
# generated dev and test sets will not have any repeated sentences. Sentences
# in the dev and test sets will appear only in a single set.
def generate_unique_dev_test(df, dev_size, test_size):
    counter = Counter(df['transcript'].values)
    idx_unique_sentences = df['transcript'].apply(lambda x: counter[x] == 1)

    if idx_unique_sentences.sum() < (dev_size + test_size):
        raise ValueError('Not enough unique sentences')

    dev_test = df[idx_unique_sentences].sample(dev_size + test_size)
    dev = dev_test[:dev_size]
    test = dev_test[dev_size:]
    train = df.drop(index=dev_test.index)

    dev_sentences = set(dev['transcript'].values)
    test_sentences = set(test['transcript'].values)
    train_sentences = set(train['transcript'].values)

    assert train_sentences.isdisjoint(dev_sentences)
    assert train_sentences.isdisjoint(test_sentences)
    assert dev_sentences.isdisjoint(test_sentences)

    return train, dev, test


# Check if file header matches exactly what's expected by TensorFlow. Note that
# even if SoX/ffmpeg/etc show the correct parameters, there are multiple header
# formats used in the wild for .wav files and TensorFlow only accepts the format
# generated by SoX, so if the header is in a differen format you'll need to
# transcode the files with SoX.
def invalid_header(file):
     with open(file, 'rb') as fin:
         audio_format, num_channels, sample_rate, bits_per_sample = struct.unpack('<xxxxxxxxxxxxxxxxxxxxHHIxxxxxxH', fin.read(36))
         return audio_format != 1 or num_channels != 1 or sample_rate != 16000 or bits_per_sample != 16


# You can do this to transcode files with different header formats:
#
# invalid = df['wav_filename'].apply(invalid_header)
# transcode_files(df, invalid)
#
def transcode_files(df, idx_to_transcode):
    df.loc[idx_to_transcode, 'wav_filename'].to_csv('/tmp/to_transcode.txt', header=False, index=False)
    subprocess.check_call(shlex.split('''cat /tmp/to_transcode.txt | xargs -n1 -P32 bash -c 'sox "$0" -t wav -r 16000 -e signed -b 16 -c 1 --endian little --compression 0.0 --no-dither "${0/.wav/_transcoded.wav}"')'''), shell=True)
    df.loc[idx_to_transcode, 'wav_filename'] = df.loc[idx_to_transcode, 'wav_filename'].replace('.wav', '_transcoded.wav')


# In case of the following TensorFlow error, and you're ABSOLUTELY sure all
# files are PCM Mono 16000 Hz, 16-bit per sample:
#
# tensorflow.python.framework.errors_impl.InvalidArgumentError: 2 root error(s) found.
#   (0) Invalid argument: Bad bytes per sample in WAV header: Expected 2 but got 4
#     [[{{node DecodeWav}}]]
#     [[tower_7/IteratorGetNext]]
#
# Use with: df['wav_filename'].apply(fix_header)
#
def fix_header(wav_filename):
     with open(wav_filename, 'r+b') as fio:
         header = bytearray(fio.read(44))
         bytes_per_sample = struct.unpack_from('<H', header[32:34])
         if bytes_per_sample != 2:
             header[32:34] = struct.pack('<H', 2) # force set 2 bytes per sample
             fio.seek(0, 0)
             fio.write(header)


# Remove files that have transcripts with characters outside of the alphabet
#
# alphabet = set('abcdef...')
# df, removed = remove_files_non_alphabetic(df, alphabet)
#
def remove_files_non_alphabetic(df, alphabet):
    alphabetic = df['transcript'].apply(lambda x: set(x) <= alphabet)
    return df[alphabetic], df[~alphabetic]
