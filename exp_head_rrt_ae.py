import random
from datetime import datetime
import os
import mlflow
import mlflow.tensorflow
import numpy as np
import tensorflow as tf

from dataload import DenseReweights as dr
from dataload import seploader as sepl
from evaluate import evaluation as eval
from evaluate.utils import count_above_threshold, plot_tsne_extended
# types for type hinting
from models import modeling
# Set the DagsHub credentials programmatically
os.environ['MLFLOW_TRACKING_USERNAME'] = 'ERUD1T3'
os.environ['MLFLOW_TRACKING_PASSWORD'] = '0b7739bcc448e3336dcc7437b505c44cc1801f9c'

# Configure MLflow to connect to DagsHub
mlflow.set_tracking_uri('https://dagshub.com/ERUD1T3/keras-functional-api.mlflow')
mlflow.set_experiment("ai_panthers")

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
    # data_path = '/home1/jmoukpe2016/keras-functional-api/cme_and_electron/data'
    data_path = './cme_and_electron/data'

    # check for gpus
    print(tf.config.list_physical_devices('GPU'))
    # Read the CSV file
    loader = sepl.SEPLoader()
    shuffled_train_x, shuffled_train_y, shuffled_val_x, \
        shuffled_val_y, shuffled_test_x, shuffled_test_y = loader.load_from_dir(data_path)

    # combine and get weights
    combined_train_x, combined_train_y = loader.combine(shuffled_train_x, shuffled_train_y, shuffled_val_x,
                                                        shuffled_val_y)
    min_norm_weight = 0.01 / len(combined_train_y)

    # get validation sample weights based on dense weights
    combined_sample_weights = dr.DenseReweights(
        combined_train_x, combined_train_y, alpha=.9, min_norm_weight=min_norm_weight, debug=False).reweights
    train_length = len(shuffled_train_y)
    val_length = len(shuffled_val_y)

    sample_weights = combined_sample_weights[:train_length]
    val_sample_weights = combined_sample_weights[train_length:train_length + val_length]

    elevateds, seps = count_above_threshold(shuffled_train_y)
    print(f'Sub-Training set: elevated events: {elevateds}  and sep events: {seps}')
    elevateds, seps = count_above_threshold(shuffled_val_y)
    print(f'Validation set: elevated events: {elevateds}  and sep events: {seps}')
    elevateds, seps = count_above_threshold(shuffled_test_y)
    print(f'Test set: elevated events: {elevateds}  and sep events: {seps}')

    for batch_size, freeze in [(292, False), (292, True), (-1, False), (-1, True)]:
        title = f'rRT+AE, {"with" if batch_size > 0 else "without"} batches, {"frozen" if freeze else "fine-tuned"} features'
        print(title)
        with mlflow.start_run(run_name=f"rRT_AE_{batch_size}_freeze_{freeze}"):
            # Automatic logging
            mlflow.tensorflow.autolog()
            # Log the batch size
            mlflow.log_param("batch_size", batch_size)
            mlflow.log_param("freeze features", freeze)
            mb = modeling.ModelBuilder()

            # create my feature extractor
            feat_reg_ae = mb.create_model(input_dim=19, feat_dim=9, output_dim=1, hiddens=[18], with_ae=True)

            # load weights to continue training
            # feature_extractor_plus_head.load_weights('model_weights_2023-09-28_18-10-52.h5')
            # print('weights model_weights_2023-09-28_18-10-52.h5 loaded successfully!')

            # Generate a timestamp
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            # training
            Options = {
                'batch_size': batch_size,  # len(shuffled_train_x), #768,
                'epochs': 100000,
                'patience': 25,
                'learning_rate': 9e-4,
            }

            # print options used
            print(Options)
            mb.train_reg_ae_heads(feat_reg_ae,
                                  shuffled_train_x, shuffled_train_y,
                                  shuffled_val_x, shuffled_val_y,
                                  combined_train_x, combined_train_y,
                                  learning_rate=Options['learning_rate'],
                                  epochs=Options['epochs'],
                                  batch_size=Options['batch_size'],
                                  patience=Options['patience'], save_tag='rrtae_stage_1_' + timestamp)

            file_path = plot_tsne_extended(feat_reg_ae, combined_train_x, combined_train_y, title,
                                           'rrtae_stage1_training_',
                                           model_type='features_reg_dec', save_tag=timestamp, seed=SEED)
            mlflow.log_artifact(file_path)
            file_path = plot_tsne_extended(feat_reg_ae, shuffled_test_x, shuffled_test_y, title,
                                           'rrtae_stage1_testing_',
                                           model_type='features_reg_dec', save_tag=timestamp, seed=SEED)
            mlflow.log_artifact(file_path)
            # add the regression head with dense weighting
            regressor = mb.add_reg_proj_head(feat_reg_ae, freeze_features=freeze)

            # training
            Options = {
                'batch_size': batch_size,  # len(shuffled_train_x), #768,
                'epochs': 100000,
                'patience': 25,
                'learning_rate': 6e-4,
            }

            # print options used
            print(Options)
            mb.train_reg_head(regressor,
                              shuffled_train_x, shuffled_train_y,
                              shuffled_val_x, shuffled_val_y,
                              combined_train_x, combined_train_y,
                              sample_weights=sample_weights,
                              sample_val_weights=val_sample_weights,
                              sample_train_weights=combined_sample_weights,
                              learning_rate=Options['learning_rate'],
                              epochs=Options['epochs'],
                              batch_size=Options['batch_size'],
                              patience=Options['patience'], save_tag='rrtae_stage_2_' + timestamp)

            file_path = plot_tsne_extended(regressor, combined_train_x, combined_train_y, title,
                                           'rrtae_stage2_training_',
                                           save_tag=timestamp, seed=SEED)
            mlflow.log_artifact(file_path)
            file_path = plot_tsne_extended(regressor, shuffled_test_x, shuffled_test_y, title, 'rrtae_stage2_testing_',
                                           save_tag=timestamp, seed=SEED)
            mlflow.log_artifact(file_path)
            ev = eval.Evaluator()
            metrics = ev.evaluate(regressor, shuffled_test_x, shuffled_test_y, title, threshold=10,
                                  save_tag='rrtae_test_' + timestamp)
            # Log each metric in the dictionary
            for key, value in metrics.items():
                if key == 'plot':
                    mlflow.log_artifact(value)  # Log the plot as an artifact
                else:
                    mlflow.log_metric(key, value)  # Log other items as metrics

            metrics = ev.evaluate(regressor, combined_train_x, combined_train_y, title, threshold=10,
                                  save_tag='rrtae_training_' + timestamp)
            # Log each metric in the dictionary
            for key, value in metrics.items():
                if key == 'plot':
                    mlflow.log_artifact(value)  # Log the plot as an artifact
                else:
                    mlflow.log_metric(key, value)  # Log other items as metrics


if __name__ == '__main__':
    main()
