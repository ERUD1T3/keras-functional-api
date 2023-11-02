import random
from datetime import datetime

# import mlflow
# import mlflow.tensorflow
import numpy as np
import tensorflow as tf

from dataload import DenseReweights as dr
from dataload import seploader as sepl
from evaluate.utils import count_above_threshold, plot_tsne_pds, split_combined_joint_weights_indices
from models import modeling

# SEEDING
SEED = 42  # seed number 

# Set NumPy seed
np.random.seed(SEED)

# Set TensorFlow seed
tf.random.set_seed(SEED)

# Set random seed
random.seed(SEED)

# mlflow.set_tracking_uri("http://127.0.0.1:5000")



def main():
    """
    Main function for testing the AI Panther
    :return: None
    """

    data_path = '/home1/jmoukpe2016/keras-functional-api/cme_and_electron/data'
    # data_path = './cme_and_electron/data'
    # check for gpus
    print(tf.config.list_physical_devices('GPU'))
    # Read the CSV file
    loader = sepl.SEPLoader()
    shuffled_train_x, shuffled_train_y, shuffled_val_x, \
        shuffled_val_y, shuffled_test_x, shuffled_test_y = loader.load_from_dir(data_path)

    # combine training and validation
    combined_train_x, combined_train_y = loader.combine(
        shuffled_train_x, shuffled_train_y, shuffled_val_x, shuffled_val_y)

    # print(f'len combined: {len(combined_train_y)}')
    min_norm_weight = 0.01 / len(combined_train_y)

    train_jweights = dr.DenseJointReweights(
        combined_train_x, combined_train_y, alpha=.9, min_norm_weight=min_norm_weight, debug=False)

    # Assuming train_jweights contains the combined joint reweighting info
    train_sample_joint_weights = train_jweights.jreweights
    train_sample_joint_weights_indices = train_jweights.jindices

    # Get lengths of original training and validation sets
    len_train = len(shuffled_train_y)
    len_val = len(shuffled_val_y)

    # Split the combined joint weights and indices back into their original training and validation parts
    (sample_joint_weights, sample_joint_weights_indices,
     val_sample_joint_weights, val_sample_joint_weights_indices) = split_combined_joint_weights_indices(
        train_sample_joint_weights, train_sample_joint_weights_indices, len_train, len_val)

    elevateds, seps = count_above_threshold(shuffled_train_y)
    print(f'Sub-Training set: elevated events: {elevateds}  and sep events: {seps}')
    elevateds, seps = count_above_threshold(shuffled_val_y)
    print(f'Validation set: elevated events: {elevateds}  and sep events: {seps}')
    elevateds, seps = count_above_threshold(shuffled_test_y)
    print(f'Test set: elevated events: {elevateds}  and sep events: {seps}')

    for batch_size in [292, len_train]:
        title = f'PDS, Dense Joint Loss, {"with" if batch_size == 292 else "without"} batches'
        print(title)
        # with mlflow.start_run(run_name=f"PDS_DL_{batch_size}"):
        # Automatic logging
        # mlflow.tensorflow.autolog()
        # Log the batch size
        # mlflow.log_param("batch_size", batch_size)

        mb = modeling.ModelBuilder()

        # create my feature extractor
        feature_extractor = mb.create_model_pds(input_dim=19, feat_dim=9, hiddens=[18])

        # plot the model
        # # mb.plot_model(feature_extractor, "pds_stage1")

        # load weights to continue training
        # feature_extractor.load_weights('model_weights_2023-09-28_18-25-47.h5')
        # print('weights loaded successfully!')
        # Generate a timestamp
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        # training
        Options = {
            'batch_size': batch_size,
            'epochs': 10000,
            'patience': 25,
            'learning_rate': 9e-2,
        }
        # print options used
        print(Options)
        mb.train_pds_dl(feature_extractor,
                        shuffled_train_x, shuffled_train_y,
                        shuffled_val_x, shuffled_val_y,
                        combined_train_x, combined_train_y,
                        sample_joint_weights=sample_joint_weights,
                        sample_joint_weights_indices=sample_joint_weights_indices,
                        val_sample_joint_weights=val_sample_joint_weights,
                        val_sample_joint_weights_indices=val_sample_joint_weights_indices,
                        train_sample_joint_weights=train_sample_joint_weights,
                        train_sample_joint_weights_indices=train_sample_joint_weights_indices,
                        learning_rate=Options['learning_rate'],
                        epochs=Options['epochs'],
                        batch_size=Options['batch_size'],
                        patience=Options['patience'], save_tag=timestamp+"_features")


        file_path = plot_tsne_pds(feature_extractor,
                                    combined_train_x,
                                    combined_train_y,
                                    title, 'training',
                                    save_tag=timestamp)
        # mlflow.log_artifact(file_path)
        print('file_path'+ file_path)
        file_path = plot_tsne_pds(feature_extractor,
                                    shuffled_test_x,
                                    shuffled_test_y,
                                    title, 'testing',
                                    save_tag=timestamp)
        # mlflow.log_artifact(file_path)
        print('file_path'+ file_path)


if __name__ == '__main__':
    main()
