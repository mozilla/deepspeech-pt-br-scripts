import pandas
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
