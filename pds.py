import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from sklearn.utils import shuffle
# types for type hinting
from models import modeling
from sklearn.manifold import TSNE
import tensorflow as tf
import random
from datetime import datetime
from dataload import seploader as sepl
from evaluate.utils import count_above_threshold, plot_tsne_and_save_with_timestamp

# SEEDING
SEED = 42  # seed number 

# Set NumPy seed
np.random.seed(SEED)

# Set TensorFlow seed
tf.random.set_seed(SEED)

# Set random seed
random.seed(SEED)


def main():
    """
    Main function for testing the AI Panther
    :return: None
    """
    title = 'PDS, with batches'
    print(title)

    # check for gpus
    tf.config.list_physical_devices('GPU')
    # Read the CSV file
    loader = sepl.SEPLoader()
    shuffled_train_x, shuffled_train_y, shuffled_val_x, \
        shuffled_val_y, shuffled_test_x, shuffled_test_y = loader.load_from_dir('./cme_and_electron/data')

    train_count = count_above_threshold(shuffled_train_y)
    val_count = count_above_threshold(shuffled_val_y)
    test_count = count_above_threshold(shuffled_test_y)

    print(f'Training set: {train_count} above the threshold')
    print(f'Validation set: {val_count} above the threshold')
    print(f'Test set: {test_count} above the threshold')

    mb = modeling.ModelBuilder()

    # create my feature extractor
    feature_extractor = mb.create_model_feat(inputs=19, feat_dim=9, hiddens=[18])

    # plot the model
    mb.plot_model(feature_extractor, "pds_stage1")

    exit()

    # load weights to continue training
    # feature_extractor.load_weights('model_weights_2023-09-28_18-25-47.h5')
    # print('weights loaded successfully!')

    # Generate a timestamp
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    # training
    Options = {
        'batch_size': 768,
        'epochs': 10000,
        'patience': 25,
        'learning_rate': 1e-3,
    }

    # print options used
    print(Options)
    mb.train_features(feature_extractor, shuffled_train_x, shuffled_train_y, shuffled_val_x, shuffled_val_y,
                      learning_rate=Options['learning_rate'],
                      epochs=Options['epochs'],
                      batch_size=Options['batch_size'],
                      patience=Options['patience'], save_tag=timestamp)

    # combine training and validation
    combined_train_x, combined_train_y = loader.combine(shuffled_train_x, shuffled_train_y, shuffled_val_x,
                                                        shuffled_val_y)

    plot_tsne_and_save_with_timestamp(feature_extractor, combined_train_x, combined_train_y, title, 'training',
                                      save_tag=timestamp)

    plot_tsne_and_save_with_timestamp(feature_extractor, shuffled_test_x, shuffled_test_y, title,'testing',
                                      save_tag=timestamp)


if __name__ == '__main__':
    main()
