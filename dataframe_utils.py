import os
import pandas
import regex as re
import subprocess
import sys
import wave

from collections import Counter


# Create (or override) a 'wav_filesize' column in the DataFrame with the size of
# each sample in the dataset.
def compute_filesize(df):
    df['wav_filesize'] = df['wav_filename'].apply(os.path.getsize)


# For a dataset where some transcripts repeat more than `limit` times, create a
# new dataset where a sentence only repeats at most `limit` times.
def limit_repeated_samples(df, limit):
    counter = Counter(df['transcript'].values)

    # No sentence repeats more than `limit` times, short-circuit
    if counter.most_common(1)[0][1] <= limit:
        return df

    # Collect samples with transcripts that repeat <= `limit` times in the dataset.
    nb_of_repeats = df['transcript'].apply(lambda x: counter[x])
    data_le_limit = df[nb_of_repeats <= limit]
    data_gt_limit = df[nb_of_repeats > limit]

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
def is_invalid_header(file):
     with open(file, 'rb') as fin:
         audio_format, num_channels, sample_rate, bits_per_sample = struct.unpack('<xxxxxxxxxxxxxxxxxxxxHHIxxxxxxH', fin.read(36))
         return audio_format != 1 or num_channels != 1 or sample_rate != 16000 or bits_per_sample != 16


# You can do this to transcode files with different header formats:
#
# invalid = df['wav_filename'].apply(is_invalid_header)
# transcode_files(df, invalid)
#
def transcode_files(df, idx_to_transcode):
    df.loc[idx_to_transcode, 'wav_filename'].to_csv('/tmp/to_transcode.txt', header=False, index=False)
    subprocess.check_call(shlex.split('''cat /tmp/to_transcode.txt | xargs -n1 -P32 bash -c 'sox "$0" -t wav -r 16000 -e signed -b 16 -c 1 --endian little --compression 0.0 --no-dither "${0/.wav/_transcoded.wav}"')'''), shell=True)
    df.loc[idx_to_transcode, 'wav_filename'] = df.loc[idx_to_transcode, 'wav_filename'].replace('.wav', '_transcoded.wav')


# In case of the following TensorFlow error, and you're ABSOLUTELY sure all
# files are PCM Mono 16000 Hz, 16-bits per sample:
#
# tensorflow.python.framework.errors_impl.InvalidArgumentError: 2 root error(s) found.
#   (0) Invalid argument: Bad bytes per sample in WAV header: Expected 2 but got 4
#     [[{{node DecodeWav}}]]
#     [[tower_7/IteratorGetNext]]
#
# Use with: df['wav_filename'].apply(fix_header_bytes_per_sample)
#
def fix_header_bytes_per_sample(wav_filename):
     with open(wav_filename, 'r+b') as fio:
         header = bytearray(fio.read(44))
         bytes_per_sample = struct.unpack_from('<H', header[32:34])
         if bytes_per_sample != 2:
             header[32:34] = struct.pack('<H', 2) # force set 2 bytes per sample
             fio.seek(0, 0)
             fio.write(header)


# Remove files that have transcripts with characters outside of the alphabet
#
#   alphabet = set('abcdef...')
#   df, removed = remove_files_non_alphabetic(df, alphabet)
#
def remove_files_non_alphabetic(df, alphabet):
    alphabetic = df['transcript'].apply(lambda x: set(x) <= alphabet)
    return df[alphabetic], df[~alphabetic]


# Remove characters in transcripts that aren't in the Letter Unicode character
# class (Punctuation, math symbols, numbers, etc).
def remove_non_letters(df):
    df['transcript']  = df['transcript'].apply(lambda x: re.sub(r'[^\p{Letter}]', '', x))


# Find corrupted files (header duration does not match file size). Example:
#
#   invalid = df['wav_filename'].apply(bad_header_for_filesize)
#   print('The following files are corrupted:')
#   print(df[invalid].values)
#
def bad_header_for_filesize(wav_filename):
    with wave.open(wav_filename, 'r') as fin:
        header_fsize = (fin.getnframes() * fin.getnchannels() * fin.getsampwidth()) + 44
    file_fsize = os.path.getsize(wav_filename)
    return header_fsize != file_fsize


# Find files that are too short for their transcript
def find_not_enough_windows(df, sample_rate=16000, win_step_ms=20, utf8=False):
    # Compute number of windows in each file
    num_samples = (df['wav_filesize'] - 44) // 2
    samples_per_window = int(sample_rate * (win_step_ms / 1000.))
    num_windows = num_samples // samples_per_window

    # Compute transcription length
    if utf8:
        str_len = df['transcript'].str.encode('utf8').str.len()
    else:
        str_len = df['transcript'].str.len()

    return num_windows >= str_len


# Compute ratio of duration to transcript len. Extreme values likely correspond
# to problematic samples (too short for transcript, or too long for transcript).
# Example of how to visualize the histogram of ratios:
#
#   ratio = duration_to_transcript_len_ratio(df)
#   ratio.hist()
#
def duration_to_transcript_len_ratio(df, sample_rate=16000, utf8=False):
    duration = (df['wav_filesize'] - 44) / 2 / sample_rate
    if utf8:
        tr_len = df['transcript'].str.encode('utf8').str.len()
    else:
        tr_len = df['transcript'].str.len()
    return duration / tr_len


# Compute RMS power from a single 16-bit per sample WAVE file
def rms(x):
    with wave.open(x) as fin:
        samples = np.frombuffer(fin.readframes(fin.getnframes()), np.int16)
        return np.sqrt(np.mean(samples**2))


# Calculate RMS power of all samples in DataFrame
def compute_rms(df):
    return df['wav_filename'].apply(rms)

