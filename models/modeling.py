##############################################################################################################
# Description: training and testing (algos, nn structure, loss functions,
# using validation loss to determine epoch number for training).
# this module should be interchangeable with other modules (
##############################################################################################################

# imports
import tensorflow as tf
from tensorflow.keras import layers, callbacks, Model
import datetime
import numpy as np
import matplotlib.pyplot as plt
from itertools import cycle

# types for type hinting
from typing import Tuple, List, Optional, Callable
from tensorflow import Tensor
from numpy import ndarray


class ModelBuilder:
    """
    Class for building a neural network model.
    """

    # class variables
    debug = False
    model = None
    hidden_arch = None
    input_size = None
    output_size = None
    lambda_coef = None

    def __init__(self, debug: bool = True) -> None:
        """
        Initialize the class variables.

        :param debug: Boolean to enable debug output.
        """
        self.debug = debug
        self.lambda_coef = 4  # coefficient for matching feature loss and regression loss

    def create_model(self, input_dim: int, feat_dim: int, output_dim: int, hiddens: List[int],
                     with_ae: bool = False) -> Model:
        """
        Create a neural network model with options for multiple heads using the Keras functional API.

        :param input_dim: Integer representing the number of input features.
        :param feat_dim: Integer representing the dimensionality of the feature (representation layer).
        :param output_dim: Integer representing the dimensionality of the output.
        :param hiddens: List of integers representing the number of nodes in each hidden layer.
        :param with_ae: Boolean flag to indicate whether to include an AutoEncoder (AE) head for input reconstruction.

        :return: The uncompiled model.
        """
        # Input layer
        input_layer = layers.Input(shape=(input_dim,))
        x = input_layer

        # Define hidden layers according to architecture
        for nodes in hiddens:
            x = layers.Dense(nodes)(x)
            x = layers.LeakyReLU()(x)

        # Define the representation layer (Z features)
        repr_layer = layers.Dense(feat_dim)(x)
        repr_layer = layers.LeakyReLU(name='repr_layer')(repr_layer)

        # Add a regression head
        regression_head = layers.Dense(output_dim, activation='linear', name='regression_head')(repr_layer)

        # Create output_dim list
        outputs_list = [repr_layer, regression_head]

        # Add a decoder (AE) head for input reconstruction if with_ae is True
        if with_ae:
            decoder_head = repr_layer
            for nodes in reversed(hiddens):
                decoder_head = layers.Dense(nodes)(decoder_head)
                decoder_head = layers.LeakyReLU()(decoder_head)
            decoder_head = layers.Dense(input_dim, activation='linear', name='decoder_head')(decoder_head)
            outputs_list.append(decoder_head)

        # Create the model, repr, reg, decoder
        model = Model(inputs=input_layer, outputs=outputs_list)

        return model

    def create_model_pds(self, input_dim: int, feat_dim: int, hiddens: List[int],
                         output_dim: Optional[int] = 1, with_reg: bool = False, with_ae: bool = False) -> Model:
        """
        Create a neural network model with optional autoencoder and regression heads.
        The base model is used for feature extraction.

        :param input_dim: Integer representing the number of input features.
        :param feat_dim: Integer representing the dimensionality of the feature (representation layer).
        :param hiddens: List of integers representing the number of nodes in each hidden layer of the encoder.
        :param output_dim: Integer representing the dimensionality of the regression output. Default is 1.
        :param with_reg: Boolean flag to add a regression head to the model. Default is False.
        :param with_ae: Boolean flag to add a decoder to the model (making it an autoencoder). Default is False.
        :return: The uncompiled model with optional heads based on flags.
        """
        # Encoder
        encoder_input = layers.Input(shape=(input_dim,))
        x = encoder_input
        for nodes in hiddens:
            x = layers.Dense(nodes)(x)
            x = layers.LeakyReLU()(x)

        x = layers.Dense(feat_dim)(x)
        x = layers.LeakyReLU()(x)
        repr_layer = NormalizeLayer(name='normalize_layer')(x)

        outputs = [repr_layer]

        # Optional Regression Head
        if with_reg:
            x_reg = repr_layer
            regression_output = layers.Dense(output_dim, activation='linear', name='regression_head')(x_reg)
            outputs.append(regression_output)

        # Optional Decoder
        if with_ae:
            x_dec = repr_layer
            for nodes in reversed(hiddens):
                x_dec = layers.Dense(nodes)(x_dec)
                x_dec = layers.LeakyReLU()(x_dec)
            decoder_output = layers.Dense(input_dim, activation='linear', name='decoder_head')(x_dec)
            outputs.append(decoder_output)

        # Complete model, repr, reg, decoder
        model = Model(inputs=encoder_input, outputs=outputs if len(outputs) > 1 else outputs[0])

        # Storing the model
        self.model = model

        return self.model

    def add_reg_proj_head(self, model: Model, output_dim: int = 1, hiddens: Optional[List[int]] = None,
                          freeze_features: bool = True, pds: bool = True) -> Model:
        """
        Add a regression head with one output unit and a projection layer to an existing model,
        replacing the existing prediction layer and optionally the decoder layer.

        :param model: The existing model
        :param output_dim: The dimensionality of the output of the regression head.
        :param freeze_features: Whether to freeze the layers of the base model or not.
        :param hiddens: List of integers representing the hidden layers for the projection.
        :param pds: Whether to adapt the model for PDS representations.
        :return: The modified model with a projection layer and a regression head.
        """

        if hiddens is None:
            hiddens = [6]

        print(f'Features are frozen: {freeze_features}')

        # Determine the layer to be kept based on whether PDS representations are used
        layer_to_keep = 'normalize_layer' if pds else 'repr_layer'

        # Remove the last layer(s) to keep only the representation layer
        new_base_model = Model(inputs=model.input, outputs=model.get_layer(layer_to_keep).output)

        # If freeze_features is True, freeze the layers of the new base model
        if freeze_features:
            for layer in new_base_model.layers:
                layer.trainable = False

        # Extract the output of the last layer of the new base model (representation layer)
        repr_output = new_base_model.output

        # Projection Layer(s)
        x_proj = repr_output
        for i, nodes in enumerate(hiddens):
            x_proj = layers.Dense(nodes, name=f"projection_layer_{i + 1}")(x_proj)
            x_proj = layers.LeakyReLU(name=f"projection_activation_{i + 1}")(x_proj)

        # Add a Dense layer with one output unit for regression
        regression_head = layers.Dense(output_dim, activation='linear', name="regression_head")(x_proj)

        # Create the new extended model
        extended_model = Model(inputs=new_base_model.input, outputs=[repr_output, regression_head])

        # If freeze_features is False, make all layers trainable
        if not freeze_features:
            for layer in extended_model.layers:
                layer.trainable = True

        return extended_model

    # def train_jointly(self,
    #                   model: Model,
    #                   X_train: Tensor,
    #                   y_train: Tensor,
    #                   y_regression: Tensor,
    #                   sample_weights: ndarray = None,
    #                   sample_joint_weights: ndarray = None,
    #                   learning_rate: float = 1e-3,
    #                   epochs: int = 100,
    #                   batch_size: int = 32,
    #                   patience: int = 9,
    #                   lambda_coef: float = 2.0) -> callbacks.History:
    #     """
    #     Train a neural network model focusing on both the feature representation and regression output.
    #
    #     :param model: The neural network model.
    #     :param X_train: Training features.
    #     :param y_train: Training labels .
    #     :param sample_weights: Sample weights for regression head.
    #     :param sample_joint_weights: Sample weights for feature representation.
    #     :param learning_rate: Learning rate for Adam optimizer.
    #     :param epochs: Number of epochs to train.
    #     :param batch_size: Size of batches during training.
    #     :param patience: Number of epochs to wait for early stopping.
    #     :param lambda_coef: Coefficient for balancing the two loss functions.
    #     :return: Training history.
    #     """
    #
    #     class WeightedLossCallback(callbacks.Callback):
    #         def __init__(self, sample_joint_weights, y_shape):
    #             self.sample_joint_weights = sample_joint_weights
    #             self.y_shape = y_shape
    #
    #         def on_train_batch_begin(self, batch, logs=None):
    #             if self.sample_joint_weights is not None:
    #                 idx1, idx2 = np.triu_indices(self.y_shape, k=1)
    #                 one_d_indices = np.ravel_multi_index((idx1, idx2), (self.y_shape, self.y_shape))
    #                 joint_weights_batch = self.sample_joint_weights[one_d_indices]
    #                 self.model.loss_weights = {'feature_head': joint_weights_batch, 'regression_head': lambda_coef}
    #
    #     # Define the losses and their weights
    #     losses = {'feature_head': self.repr_loss, 'regression_head': 'mse'}
    #     loss_weights = {'feature_head': 1.0, 'regression_head': lambda_coef}
    #
    #     # TensorBoard setup
    #     log_dir = "logs/fit/" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    #     tensorboard_cb = callbacks.TensorBoard(log_dir=log_dir, histogram_freq=1)
    #
    #     # Early stopping setup
    #     early_stopping_cb = callbacks.EarlyStopping(monitor='val_loss', patience=patience, restore_best_weights=True)
    #
    #     # Weighted loss callback setup
    #     weighted_loss_cb = WeightedLossCallback(sample_joint_weights, y_train.shape[0])
    #
    #     # Callback list
    #     callback_list = [tensorboard_cb, early_stopping_cb]
    #
    #     if sample_joint_weights is not None:
    #         callback_list.append(weighted_loss_cb)
    #
    #     # Compile the model
    #     model.compile(optimizer=tf.keras.optimizers.Adam(learning_rate), loss=losses, loss_weights=loss_weights)
    #
    #     # Fit the model
    #     history = model.fit(X_train, {'feature_head': y_train, 'regression_head': y_regression},
    #                         sample_weight={'feature_head': sample_joint_weights, 'regression_head': sample_weights},
    #                         epochs=epochs, batch_size=batch_size,
    #                         validation_split=0.3, callbacks=callback_list)
    #
    #     # Get the best epoch
    #     best_epoch = np.argmin(history.history['val_loss']) + 1
    #
    #     # Plotting the loss
    #     plt.figure(figsize=(12, 6))
    #
    #     plt.subplot(1, 2, 1)
    #     plt.plot(history.history['feature_head_loss'], label='Feature Training Loss')
    #     plt.plot(history.history['val_feature_head_loss'], label='Feature Validation Loss')
    #     plt.xlabel('Epoch')
    #     plt.ylabel('Loss')
    #     plt.title('Feature Head Loss')
    #     plt.legend()
    #
    #     plt.subplot(1, 2, 2)
    #     plt.plot(history.history['regression_head_loss'], label='Regression Training Loss')
    #     plt.plot(history.history['val_regression_head_loss'], label='Regression Validation Loss')
    #     plt.xlabel('Epoch')
    #     plt.ylabel('Loss')
    #     plt.title('Regression Head Loss')
    #     plt.legend()
    #
    #     plt.tight_layout()
    #     plt.show()
    #
    #     return history

    def train_pds(self,
                  model: Model,
                  X_train: Tensor,
                  y_train: Tensor,
                  X_val: Tensor,
                  y_val: Tensor,
                  learning_rate: float = 1e-3,
                  epochs: int = 100,
                  batch_size: int = 32,
                  patience: int = 9,
                  save_tag=None) -> callbacks.History:
        """
        Trains the model and returns the training history.

        :param save_tag: tag to use for saving experiments
        :param model: The TensorFlow model to train.
        :param X_train: The training feature set.
        :param y_train: The training labels.
        :param X_val: Validation features.
        :param y_val: Validation labels.
        :param learning_rate: The learning rate for the Adam optimizer.
        :param epochs: The maximum number of epochs for training.
        :param batch_size: The batch size for training.
        :param patience: The number of epochs with no improvement to wait before early stopping.
        :return: The training history as a History object.
        """

        # Setup TensorBoard
        log_dir = "logs/fit/" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        tensorboard_cb = callbacks.TensorBoard(log_dir=log_dir, histogram_freq=1)

        print("Run the command line:\n tensorboard --logdir logs/fit")

        # Setup early stopping
        early_stopping_cb = callbacks.EarlyStopping(monitor='val_loss', patience=patience, restore_best_weights=True)

        # checkpoint callback
        # Setup model checkpointing
        checkpoint_cb = callbacks.ModelCheckpoint(f"model_weights_{str(save_tag)}.h5", save_weights_only=True)

        # Include weighted_loss_cb in callbacks only if sample_joint_weights is not None
        callback_list = [tensorboard_cb, early_stopping_cb, checkpoint_cb]

        # Compile the model
        model.compile(optimizer=tf.keras.optimizers.Adam(learning_rate=learning_rate), loss=self.repr_loss)

        # First train the model with a validation set to determine the best epoch
        history = model.fit(X_train, y_train,
                            epochs=epochs,
                            batch_size=batch_size,
                            validation_data=(X_val, y_val),
                            callbacks=callback_list)

        # Get the best epoch from early stopping
        best_epoch = np.argmin(history.history['val_loss']) + 1

        # Plot training loss and validation loss
        plt.plot(history.history['loss'], label='Training Loss')
        plt.plot(history.history['val_loss'], label='Validation Loss')
        plt.xlabel('Epoch')
        plt.ylabel('Loss')
        plt.title('Training and Validation Loss Over Epochs')
        plt.legend()
        file_path = f"training_plot_{str(save_tag)}.png"
        plt.savefig(file_path)
        plt.close()

        # Retrain the model on the combined dataset (training + validation) to the best epoch found
        X_combined = np.concatenate((X_train, X_val), axis=0)
        y_combined = np.concatenate((y_train, y_val), axis=0)

        # model.compile(optimizer=tf.keras.optimizers.Adam(learning_rate=learning_rate), loss=self.repr_loss)
        model.fit(X_combined, y_combined, epochs=best_epoch, batch_size=batch_size,
                  callbacks=[tensorboard_cb, checkpoint_cb])

        # save the model weights
        model.save_weights(f"model_weights_{str(save_tag)}.h5")

        return history

    def process_batch_weights(self, batch_indices: np.ndarray, all_weights: np.ndarray,
                              all_weight_indices: List[Tuple[int, int]]) -> np.ndarray:
        """
        Process a batch of indices to return the corresponding joint weights.

        :param batch_indices: A batch of sample indices.
        :param all_weights: An array containing all joint weights for the dataset.
        :param all_weight_indices: A list of tuples, each containing a pair of indices for which a joint weight exists.
        :return: An array containing joint weights corresponding to the batch of indices.
        """
        batch_weights = []
        for i in batch_indices:
            for j in batch_indices:
                if i < j:  # Only consider pairs (i, j) where i < j
                    try:
                        weight_idx = all_weight_indices.index((i, j))
                    except ValueError:
                        continue  # Skip if the pair doesn't have a corresponding weight
                    batch_weights.append(all_weights[weight_idx])  # Append the weight for this pair

        return np.array(batch_weights)

    def train_for_one_epoch(self,
                            model: tf.keras.Model,
                            optimizer: tf.keras.optimizers.Optimizer,
                            loss_fn,
                            X: np.ndarray,
                            y: np.ndarray,
                            batch_size: int,
                            all_weights: Optional[np.ndarray] = None,
                            all_weight_indices: Optional[List[Tuple[int, int]]] = None,
                            training: bool = True) -> float:
        """
        Train or evaluate the model for one epoch.

        :param model: The model to train or evaluate.
        :param optimizer: The optimizer to use.
        :param loss_fn: The loss function to use.
        :param X: The feature set.
        :param y: The labels.
        :param batch_size: The batch size for training or evaluation.
        :param all_weights: Optional array containing all joint weights for the dataset.
        :param all_weight_indices: Optional list of tuples, each containing a pair of indices for which a joint weight exists.
        :param training: Whether to apply training (True) or run evaluation (False).
        :return: The average loss for the epoch.
        """
        epoch_loss = 0.0
        num_batches = 0
        total_batch_size = len(X) // batch_size + 1

        for batch_idx in range(0, len(X), batch_size):
            batch_X = X[batch_idx:batch_idx + batch_size]
            batch_y = y[batch_idx:batch_idx + batch_size]

            # Get the corresponding joint weights for this batch
            batch_weights = None
            if all_weights is not None and all_weight_indices is not None:
                batch_weights = self.process_batch_weights(
                    np.arange(batch_idx, batch_idx + batch_size), all_weights, all_weight_indices)

            with tf.GradientTape() as tape:
                predictions = model(batch_X, training=training)
                loss = loss_fn(batch_y, predictions, sample_weights=batch_weights)

            if training:
                gradients = tape.gradient(loss, model.trainable_variables)
                optimizer.apply_gradients(zip(gradients, model.trainable_variables))

            epoch_loss += loss.numpy()
            num_batches += 1

            print(f"{num_batches - 1}/{total_batch_size}")

        return epoch_loss / num_batches

    def train_for_one_epoch_mh(
            self,
            model: tf.keras.Model,
            optimizer: tf.keras.optimizers.Optimizer,
            primary_loss_fn,
            X: np.ndarray,
            y: np.ndarray,
            batch_size: int,
            gamma_coeff: Optional[float] = None,
            lambda_coeff: Optional[float] = None,
            sample_weights: Optional[np.ndarray] = None,
            all_weights: Optional[np.ndarray] = None,
            all_weight_indices: Optional[List[Tuple[int, int]]] = None,
            with_reg=False,
            with_ae=False,
            training: bool = True) -> float:
        """
        Train the model for one epoch.

        :param with_ae:
        :param with_reg:
        :param model: The model to train.
        :param optimizer: The optimizer to use.
        :param primary_loss_fn: The primary loss function to use.
        :param X: The feature set.
        :param y: The labels.
        :param batch_size: The batch size for training.
        :param gamma_coeff: Coefficient for the regressor loss.
        :param lambda_coeff: Coefficient for the decoder loss.
        :param sample_weights: Individual sample weights.
        :param all_weights: Optional array containing all joint weights for the dataset.
        :param all_weight_indices: Optional list of tuples, each containing a pair of indices for which a joint weight exists.
        :param training: Whether to apply training or evaluation (default is True for training).
        :return: The average loss for the epoch.
        """

        epoch_loss = 0.0
        num_batches = 0

        for batch_idx in range(0, len(X), batch_size):
            batch_X = X[batch_idx:batch_idx + batch_size]
            batch_y = y[batch_idx:batch_idx + batch_size]
            batch_sample_weights = None if sample_weights is None \
                else sample_weights[batch_idx:batch_idx + batch_size]

            # Get the corresponding joint weights for this batch
            batch_weights = None
            if all_weights is not None and all_weight_indices is not None:
                batch_weights = self.process_batch_weights(
                    np.arange(batch_idx, batch_idx + batch_size), all_weights, all_weight_indices)

            with tf.GradientTape() as tape:
                outputs = model(batch_X, training=training)

                # Unpack the outputs based on the model configuration
                if with_reg and with_ae:
                    primary_predictions, regressor_predictions, decoder_predictions = outputs
                elif with_reg:
                    primary_predictions, regressor_predictions = outputs
                    decoder_predictions = None
                elif with_ae:
                    primary_predictions, decoder_predictions = outputs
                    regressor_predictions = None
                else:
                    primary_predictions = outputs
                    regressor_predictions, decoder_predictions = None, None

                # Primary loss
                primary_loss = primary_loss_fn(batch_y, primary_predictions, sample_weights=batch_weights)

                # Regressor loss
                regressor_loss = 0
                if with_reg and gamma_coeff is not None:
                    regressor_loss = tf.keras.losses.mean_squared_error(batch_y, regressor_predictions)
                    if batch_sample_weights is not None:
                        regressor_loss = tf.reduce_sum(regressor_loss * batch_sample_weights) / tf.reduce_sum(
                            batch_sample_weights)
                    regressor_loss *= gamma_coeff

                # Decoder loss
                decoder_loss = 0
                if with_ae and lambda_coeff is not None:
                    decoder_loss = tf.keras.losses.mean_squared_error(batch_X, decoder_predictions)
                    decoder_loss *= lambda_coeff

                # Total loss
                total_loss = primary_loss + regressor_loss + decoder_loss

            if training:
                gradients = tape.gradient(total_loss, model.trainable_variables)
                optimizer.apply_gradients(zip(gradients, model.trainable_variables))

            epoch_loss += total_loss.numpy()
            num_batches += 1

            print(f"{num_batches}/{len(X) // batch_size}")

        return epoch_loss / num_batches

    def train_pds_dl(self,
                     model: tf.keras.Model,
                     X_train: np.ndarray,
                     y_train: np.ndarray,
                     X_val: np.ndarray,
                     y_val: np.ndarray,
                     sample_joint_weights: Optional[np.ndarray] = None,
                     sample_joint_weights_indices: Optional[List[Tuple[int, int]]] = None,
                     val_sample_joint_weights: Optional[np.ndarray] = None,
                     val_sample_joint_weights_indices: Optional[List[Tuple[int, int]]] = None,
                     learning_rate: float = 1e-3,
                     epochs: int = 100,
                     batch_size: int = 32,
                     patience: int = 9,
                     save_tag: Optional[str] = None) -> dict:
        """
        Custom training loop to train the model and returns the training history.

        :param model: The TensorFlow model to train.
        :param X_train: The training feature set.
        :param y_train: The training labels.
        :param X_val: Validation features.
        :param y_val: Validation labels.
        :param sample_joint_weights: The reweighting factors for pairs of labels in training set.
        :param sample_joint_weights_indices: Indices of the reweighting factors in training set.
        :param val_sample_joint_weights: The reweighting factors for pairs of labels in validation set.
        :param val_sample_joint_weights_indices: Indices of the reweighting factors in validation set.
        :param learning_rate: The learning rate for the Adam optimizer.
        :param epochs: The maximum number of epochs for training.
        :param batch_size: The batch size for training.
        :param patience: The number of epochs with no improvement to wait before early stopping.
        :param save_tag: Tag to use for saving experiments.
        :return: The training history as a dictionary.
        """

        # Initialize early stopping and best epoch variables
        best_val_loss = float('inf')
        best_epoch = 0
        epochs_without_improvement = 0

        # Initialize TensorBoard
        log_dir = "logs/fit/" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        tensorboard_cb = tf.keras.callbacks.TensorBoard(log_dir=log_dir, histogram_freq=1)

        print("Run the command line:\n tensorboard --logdir logs/fit")

        # Optimizer and history initialization
        optimizer = tf.keras.optimizers.Adam(learning_rate=learning_rate)
        history = {'loss': [], 'val_loss': []}

        for epoch in range(epochs):
            train_loss = self.train_for_one_epoch(
                model, optimizer, self.repr_loss_dl, X_train, y_train,
                batch_size, all_weights=sample_joint_weights,
                all_weight_indices=sample_joint_weights_indices)

            val_loss = self.train_for_one_epoch(
                model, optimizer, self.repr_loss_dl, X_val, y_val,
                batch_size, all_weights=val_sample_joint_weights,
                all_weight_indices=val_sample_joint_weights_indices, training=False)

            # Log and save epoch losses
            history['loss'].append(train_loss)
            history['val_loss'].append(val_loss)

            print(f"Epoch {epoch + 1}/{epochs}, Loss: {train_loss}, Validation Loss: {val_loss}")

            # Early stopping logic
            if val_loss < best_val_loss:
                best_val_loss = val_loss
                best_epoch = epoch
                epochs_without_improvement = 0
                # Save the model weights
                model.save_weights(f"best_model_weights_{str(save_tag)}.h5")
            else:
                epochs_without_improvement += 1
                if epochs_without_improvement >= patience:
                    print("Early stopping triggered.")
                    break

        # Plotting the losses
        plt.plot(history['loss'], label='Training Loss')
        plt.plot(history['val_loss'], label='Validation Loss')
        plt.xlabel('Epoch')
        plt.ylabel('Loss')
        plt.title('Training and Validation Loss Over Epochs')
        plt.legend()
        plt.savefig(f"training_plot_{str(save_tag)}.png")
        plt.close()

        # Retraining on the combined dataset
        print(f"Retraining to the best epoch: {best_epoch}")

        # Combine X_train and X_val, y_train and y_val, and also the sample weights
        X_combined = np.concatenate([X_train, X_val])
        y_combined = np.concatenate([y_train, y_val])
        combined_sample_weights = None
        combined_sample_weights_indices = None
        if sample_joint_weights is not None and val_sample_joint_weights is not None:
            combined_sample_weights = np.concatenate([sample_joint_weights, val_sample_joint_weights])

            # Update val_sample_joint_weights_indices to reflect their new positions in the combined array
            val_sample_joint_weights_indices_updated = [(i + len(X_train), j + len(X_train)) for (i, j) in
                                                        val_sample_joint_weights_indices]

            # Concatenate the indices
            combined_sample_weights_indices = sample_joint_weights_indices + val_sample_joint_weights_indices_updated

        # Reset history for retraining
        retrain_history = {'loss': []}

        # Retrain up to the best epoch
        for epoch in range(best_epoch):
            retrain_loss = self.train_for_one_epoch(
                model, optimizer, self.repr_loss_dl, X_combined, y_combined,
                batch_size, all_weights=combined_sample_weights,
                all_weight_indices=combined_sample_weights_indices)

            # Log the retrain loss
            retrain_history['loss'].append(retrain_loss)

            print(f"Retrain Epoch {epoch + 1}/{best_epoch}, Loss: {retrain_loss}")

        # Save the final model
        model.save_weights(f"final_model_weights_{str(save_tag)}.h5")

        return history

    def train_pds_dl_heads(self,
                           model: tf.keras.Model,
                           X_train: np.ndarray,
                           y_train: np.ndarray,
                           X_val: np.ndarray,
                           y_val: np.ndarray,
                           sample_joint_weights: Optional[np.ndarray] = None,
                           sample_joint_weights_indices: Optional[List[Tuple[int, int]]] = None,
                           val_sample_joint_weights: Optional[np.ndarray] = None,
                           val_sample_joint_weights_indices: Optional[List[Tuple[int, int]]] = None,
                           sample_weights: Optional[np.ndarray] = None,
                           val_sample_weights: Optional[np.ndarray] = None,
                           with_reg: bool = False,
                           with_ae: bool = False,
                           learning_rate: float = 1e-3,
                           epochs: int = 100,
                           batch_size: int = 32,
                           patience: int = 9,
                           save_tag: Optional[str] = None) -> dict:
        """
        Custom training loop to train the model and returns the training history.

        :param with_ae:
        :param with_reg:
        :param sample_weights:
        :param val_sample_weights:
        :param model: The TensorFlow model to train.
        :param X_train: The training feature set.
        :param y_train: The training labels.
        :param X_val: Validation features.
        :param y_val: Validation labels.
        :param sample_joint_weights: The reweighting factors for pairs of labels in training set.
        :param sample_joint_weights_indices: Indices of the reweighting factors in training set.
        :param val_sample_joint_weights: The reweighting factors for pairs of labels in validation set.
        :param val_sample_joint_weights_indices: Indices of the reweighting factors in validation set.
        :param learning_rate: The learning rate for the Adam optimizer.
        :param epochs: The maximum number of epochs for training.
        :param batch_size: The batch size for training.
        :param patience: The number of epochs with no improvement to wait before early stopping.
        :param save_tag: Tag to use for saving experiments.
        :return: The training history as a dictionary.
        """

        # Initialize early stopping and best epoch variables
        best_val_loss = float('inf')
        best_epoch = 0
        epochs_without_improvement = 0

        gamma_coeff = 1
        lambda_coeff = 1

        # Initialize TensorBoard
        log_dir = "logs/fit/" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        tensorboard_cb = tf.keras.callbacks.TensorBoard(log_dir=log_dir, histogram_freq=1)

        print("Run the command line:\n tensorboard --logdir logs/fit")

        # Optimizer and history initialization
        optimizer = tf.keras.optimizers.Adam(learning_rate=learning_rate)
        history = {'loss': [], 'val_loss': []}

        for epoch in range(epochs):
            train_loss = self.train_for_one_epoch_mh(
                model, optimizer, self.repr_loss_dl, X_train, y_train,
                batch_size, gamma_coeff=gamma_coeff, lambda_coeff=lambda_coeff,
                sample_weights=sample_weights, all_weights=sample_joint_weights,
                all_weight_indices=sample_joint_weights_indices, with_reg=with_reg, with_ae=with_ae)

            val_loss = self.train_for_one_epoch_mh(
                model, optimizer, self.repr_loss_dl, X_val, y_val,
                batch_size, gamma_coeff=gamma_coeff, lambda_coeff=lambda_coeff,
                sample_weights=val_sample_weights, all_weights=val_sample_joint_weights,
                all_weight_indices=val_sample_joint_weights_indices, with_reg=with_reg, with_ae=with_ae,
                training=False)

            # Log and save epoch losses
            history['loss'].append(train_loss)
            history['val_loss'].append(val_loss)

            print(f"Epoch {epoch + 1}/{epochs}, Loss: {train_loss}, Validation Loss: {val_loss}")

            # Early stopping logic
            if val_loss < best_val_loss:
                best_val_loss = val_loss
                best_epoch = epoch
                epochs_without_improvement = 0
                # Save the model weights
                model.save_weights(f"best_model_weights_{str(save_tag)}.h5")
            else:
                epochs_without_improvement += 1
                if epochs_without_improvement >= patience:
                    print("Early stopping triggered.")
                    break

        # Plotting the losses
        plt.plot(history['loss'], label='Training Loss')
        plt.plot(history['val_loss'], label='Validation Loss')
        plt.xlabel('Epoch')
        plt.ylabel('Loss')
        plt.title('Training and Validation Loss Over Epochs')
        plt.legend()
        plt.savefig(f"training_plot_{str(save_tag)}.png")
        plt.close()

        # Retraining on the combined dataset
        print(f"Retraining to the best epoch: {best_epoch}")

        # Combine X_train and X_val, y_train and y_val, and also the sample weights
        X_combined = np.concatenate([X_train, X_val])
        y_combined = np.concatenate([y_train, y_val])

        combined_sample_weights = None
        if sample_weights is not None and val_sample_weights is not None:
            combined_sample_weights = np.concatenate([sample_weights, val_sample_weights])

        combined_sample_joint_weights = None
        combined_sample_joint_weights_indices = None
        if sample_joint_weights is not None and val_sample_joint_weights is not None:
            combined_sample_joint_weights = np.concatenate([sample_joint_weights, val_sample_joint_weights])

            # Update val_sample_joint_weights_indices to reflect their new positions in the combined array
            val_sample_joint_weights_indices_updated = [(i + len(X_train), j + len(X_train)) for (i, j) in
                                                        val_sample_joint_weights_indices]

            # Concatenate the indices
            combined_sample_joint_weights_indices = sample_joint_weights_indices + val_sample_joint_weights_indices_updated

        # Reset history for retraining
        retrain_history = {'loss': []}

        # Retrain up to the best epoch
        for epoch in range(best_epoch):
            retrain_loss = self.train_for_one_epoch_mh(
                model, optimizer, self.repr_loss_dl, X_combined, y_combined,
                batch_size, gamma_coeff=gamma_coeff, lambda_coeff=lambda_coeff,
                sample_weights=combined_sample_weights,
                all_weights=combined_sample_joint_weights,
                all_weight_indices=combined_sample_joint_weights_indices,
                with_reg=with_reg, with_ae=with_ae)

            # Log the retrain loss
            retrain_history['loss'].append(retrain_loss)
            print(f"Retrain Epoch {epoch + 1}/{best_epoch}, Loss: {retrain_loss}")

        # Save the final model
        model.save_weights(f"final_model_weights_{str(save_tag)}.h5")

        return history

    def custom_data_generator(self, X, y, batch_size):
        """
        Yields batches of data such that the last two samples in each batch
        have target labels above ln(10), and the remaining have labels below ln(10).
        Below-threshold samples cycle through before repeating.
        """
        above_threshold_indices = np.where(y > np.log(10))[0]
        below_threshold_indices = np.where(y <= np.log(10))[0]

        # Create an iterator that will cycle through the below_threshold_indices
        cyclic_below_threshold = cycle(below_threshold_indices)

        while True:
            # Select random above-threshold indices
            batch_indices_above = np.random.choice(above_threshold_indices, 2, replace=False)

            # Select (batch_size - 2) below-threshold indices in a cyclic manner
            batch_indices_below = [next(cyclic_below_threshold) for _ in range(batch_size - 2)]

            batch_indices = np.concatenate([batch_indices_below, batch_indices_above])

            batch_X = X[batch_indices]
            batch_y = y[batch_indices]

            # Shuffle the entire batch
            indices = np.arange(batch_X.shape[0])
            np.random.shuffle(indices)
            batch_X = batch_X[indices]
            batch_y = batch_y[indices]

            yield batch_X, batch_y

    def train_features_injection(self,
                                 model: Model,
                                 X_train: Tensor,
                                 y_train: Tensor,
                                 X_val: Tensor,
                                 y_val: Tensor,
                                 learning_rate: float = 1e-3,
                                 epochs: int = 100,
                                 batch_size: int = 32,
                                 patience: int = 9) -> callbacks.History:
        """
        Trains the model and returns the training history. injection of rare examples

        :param model: The TensorFlow model to train.
        :param X_train: The training feature set.
        :param y_train: The training labels.
        :param X_val: Validation features.
        :param y_val: Validation labels.
        :param learning_rate: The learning rate for the Adam optimizer.
        :param epochs: The maximum number of epochs for training.
        :param batch_size: The batch size for training.
        :param patience: The number of epochs with no improvement to wait before early stopping.
        :return: The training history as a History object.
        """

        # Create custom data generators for training and validation
        train_gen = self.custom_data_generator(X_train, y_train, batch_size)
        val_gen = self.custom_data_generator(X_val, y_val, batch_size)

        train_steps = len(y_train) // batch_size
        val_steps = len(y_val) // batch_size if len(y_val) > batch_size else len(y_val)

        # Setup TensorBoard
        log_dir = "logs/fit/" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        tensorboard_cb = callbacks.TensorBoard(log_dir=log_dir, histogram_freq=1)

        print("Run the command line:\n tensorboard --logdir logs/fit")

        # Setup early stopping
        early_stopping_cb = callbacks.EarlyStopping(monitor='val_loss', patience=patience, restore_best_weights=True)

        # checkpoint callback
        # Setup model checkpointing
        checkpoint_cb = callbacks.ModelCheckpoint("model_weights.h5", save_weights_only=True)
        # Create an instance of the custom callback

        # Include weighted_loss_cb in callbacks only if sample_joint_weights is not None
        callback_list = [tensorboard_cb, early_stopping_cb, checkpoint_cb]

        # Compile the model
        model.compile(optimizer=tf.keras.optimizers.Adam(learning_rate=learning_rate), loss=self.repr_loss)

        # First train the model with a validation set to determine the best epoch
        history = model.fit(train_gen,
                            steps_per_epoch=train_steps,
                            validation_data=val_gen,
                            validation_steps=val_steps,
                            epochs=epochs,
                            batch_size=batch_size,
                            callbacks=callback_list)

        # Get the best epoch from early stopping
        best_epoch = np.argmin(history.history['val_loss']) + 1

        # Plot training loss and validation loss
        plt.plot(history.history['loss'], label='Training Loss')
        plt.plot(history.history['val_loss'], label='Validation Loss')
        plt.xlabel('Epoch')
        plt.ylabel('Loss')
        plt.title('Training and Validation Loss Over Epochs')
        plt.legend()
        plt.show()

        # Retrain the model on the combined dataset (training + validation) to the best epoch found
        X_combined = np.concatenate((X_train, X_val), axis=0)
        y_combined = np.concatenate((y_train, y_val), axis=0)

        # Create custom generators for combined data
        train_gen_comb = self.custom_data_generator(X_combined, y_combined, batch_size)

        # Calculate the number of steps per epoch for training
        train_steps_comb = len(X_combined) // batch_size

        model.compile(optimizer=tf.keras.optimizers.Adam(learning_rate=learning_rate), loss=self.repr_loss)

        model.fit(train_gen_comb, steps_per_epoch=train_steps_comb, epochs=best_epoch, batch_size=batch_size,
                  callbacks=[tensorboard_cb, checkpoint_cb])

        return history

    # def train_features_fast(self,
    #                         model: Model,
    #                         X_train: Tensor,
    #                         y_train: Tensor,
    #                         X_val: Tensor,
    #                         y_val: Tensor,
    #                         sample_joint_weights: ndarray = None,
    #                         learning_rate: float = 1e-3,
    #                         epochs: int = 100,
    #                         batch_size: int = 32,
    #                         patience: int = 9) -> callbacks.History:
    #     """
    #     Trains the model and returns the training history.
    #     TODO: fix this issue where loss values are not correct
    #     :param model: The TensorFlow model to train.
    #     :param X_train: The training feature set.
    #     :param y_train: The training labels.
    #     :param X_val: Validation features.
    #     :param y_val: Validation labels.
    #     :param sample_joint_weights: The reweighting factors for pairs of labels.
    #     :param learning_rate: The learning rate for the Adam optimizer.
    #     :param epochs: The maximum number of epochs for training.
    #     :param batch_size: The batch size for training.
    #     :param patience: The number of epochs with no improvement to wait before early stopping.
    #     :return: The training history as a History object.
    #     """
    #
    #     # Setup TensorBoard
    #     log_dir = "logs/fit/" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    #     tensorboard_cb = callbacks.TensorBoard(log_dir=log_dir, histogram_freq=1)
    #
    #     print("Run the command line:\n tensorboard --logdir logs/fit")
    #
    #     # Setup early stopping
    #     early_stopping_cb = callbacks.EarlyStopping(monitor='val_loss', patience=patience, restore_best_weights=True)
    #
    #     # In your Callback
    #     class WeightedLossCallback(callbacks.Callback):
    #         def on_train_batch_begin(self, batch, logs=None):
    #             idx1, idx2 = np.triu_indices(len(y_train), k=1)
    #             one_d_indices = [map_to_1D_idx(i, j, len(y_train)) for i, j in zip(idx1, idx2)]
    #             joint_weights_batch = sample_joint_weights[one_d_indices]  # Retrieve weights for this batch
    #             self.model.loss_weights = joint_weights_batch  # Set loss weights for this batch
    #
    #     # Create an instance of the custom callback
    #     weighted_loss_cb = WeightedLossCallback()
    #
    #     # Include weighted_loss_cb in callbacks only if sample_joint_weights is not None
    #     callback_list = [tensorboard_cb, early_stopping_cb]
    #     if sample_joint_weights is not None:
    #         callback_list.append(weighted_loss_cb)
    #
    #     # Compile the model
    #     model.compile(optimizer=tf.keras.optimizers.Adam(learning_rate=learning_rate), loss=self.repr_loss_fast)
    #
    #     # First train the model with a validation set to determine the best epoch
    #     history = model.fit(X_train, y_train,
    #                         epochs=epochs,
    #                         batch_size=batch_size,
    #                         validation_data=(X_val, y_val),
    #                         callbacks=callback_list)
    #
    #     # Get the best epoch from early stopping
    #     best_epoch = np.argmin(history.history['val_loss']) + 1
    #
    #     # Plot training loss and validation loss
    #     plt.plot(history.history['loss'], label='Training Loss')
    #     plt.plot(history.history['val_loss'], label='Validation Loss')
    #     plt.xlabel('Epoch')
    #     plt.ylabel('Loss')
    #     plt.title('Training and Validation Loss Over Epochs')
    #     plt.legend()
    #     plt.show()
    #
    #     # Retrain the model on the combined dataset (training + validation) to the best epoch found
    #     X_combined = np.concatenate((X_train, X_val), axis=0)
    #     y_combined = np.concatenate((y_train, y_val), axis=0)
    #
    #     if sample_joint_weights is not None:
    #         sample_joint_weights_combined = np.concatenate((sample_joint_weights, sample_joint_weights), axis=0)
    #
    #     model.compile(optimizer=tf.keras.optimizers.Adam(learning_rate=learning_rate), loss=self.repr_loss_fast)
    #     if sample_joint_weights is not None:
    #         model.fit(X_combined, y_combined, epochs=best_epoch, batch_size=batch_size, callbacks=[weighted_loss_cb])
    #     else:
    #         model.fit(X_combined, y_combined, epochs=best_epoch, batch_size=batch_size)
    #
    #     return history

    def train_reg_head(self,
                       model: Model,
                       X_train: ndarray,
                       y_train: ndarray,
                       X_val: ndarray,
                       y_val: ndarray,
                       sample_weights: Optional[ndarray] = None,
                       sample_val_weights: Optional[ndarray] = None,
                       learning_rate: float = 1e-3,
                       epochs: int = 100,
                       batch_size: int = 32,
                       patience: int = 9,
                       save_tag=None) -> callbacks.History:
        """
        Train a neural network model focusing only on the regression output.
        Include reweighting for balancing the loss.

        :param save_tag:
        :param model: The neural network model.
        :param X_train: Training features.
        :param y_train: Training labels.
        :param X_val: Validation features.
        :param y_val: Validation labels.
        :param sample_weights: Sample weights for training set.
        :param sample_val_weights: Sample weights for validation set.
        :param learning_rate: Learning rate for Adam optimizer.
        :param epochs: Number of epochs.
        :param batch_size: Batch size.
        :param patience: Number of epochs for early stopping.
        :return: Training history.
        """

        # Setup TensorBoard
        log_dir = "logs/fit/" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        tensorboard_cb = callbacks.TensorBoard(log_dir=log_dir, histogram_freq=1)

        print("Run the command line:\n tensorboard --logdir logs/fit")

        # Early stopping callback
        early_stopping_cb = callbacks.EarlyStopping(monitor='val_regression_head_loss', patience=patience,
                                                    restore_best_weights=True)
        # Setup model checkpointing
        checkpoint_cb = callbacks.ModelCheckpoint(f"model_weights_{str(save_tag)}.h5", save_weights_only=True)
        # Compile the model
        model.compile(optimizer=tf.keras.optimizers.Adam(learning_rate=learning_rate), loss={'regression_head': 'mse'})

        # Train the model with a validation set
        history = model.fit(X_train, {'regression_head': y_train},
                            sample_weight=sample_weights,
                            epochs=epochs,
                            batch_size=batch_size,
                            validation_data=(X_val, {'regression_head': y_val}, sample_val_weights),
                            callbacks=[tensorboard_cb, early_stopping_cb, checkpoint_cb])

        # Find the best epoch from early stopping
        best_epoch = np.argmin(history.history['val_regression_head_loss']) + 1

        # Plot training and validation loss
        plt.plot(history.history['regression_head_loss'], label='Training Loss')
        plt.plot(history.history['val_regression_head_loss'], label='Validation Loss')
        plt.xlabel('Epoch')
        plt.ylabel('Loss')
        plt.title('Training and Validation Loss Over Epochs')
        plt.legend()
        file_path = f"training_reg_plot_{str(save_tag)}.png"
        plt.savefig(file_path)
        plt.close()

        # Combine training and validation data for final training
        X_full = np.concatenate([X_train, X_val], axis=0)
        y_full = np.concatenate([y_train, y_val], axis=0)

        # Combine sample weights if provided
        if sample_weights is not None and sample_val_weights is not None:
            full_sample_weights = np.concatenate([sample_weights, sample_val_weights], axis=0)
        else:
            full_sample_weights = None

        # Retrain the model to the best epoch using combined data
        model.fit(X_full, {'regression_head': y_full},
                  sample_weight=full_sample_weights,
                  epochs=best_epoch,
                  batch_size=batch_size,
                  callbacks=[tensorboard_cb, checkpoint_cb])

        # save the model weights
        model.save_weights(f"extended_model_weights_{str(save_tag)}.h5")

        return history

    def estimate_lambda_coef(self, model, X_train, y_train, X_val, y_val,
                             sample_weights=None, sample_val_weights=None,
                             learning_rate=1e-3, n_epochs=10, batch_size=32):
        """
        Estimate the lambda coefficient for balancing the regression and decoder losses.

        :param model: The neural network model.
        :param X_train: Training features.
        :param y_train: Training labels.
        :param X_val: Validation features.
        :param y_val: Validation labels.
        :param sample_weights: Sample weights for training set.
        :param sample_val_weights: Sample weights for validation set.
        :param learning_rate: Learning rate for Adam optimizer.
        :param n_epochs: Number of epochs to train each branch for lambda estimation.
        :param batch_size: Batch size.
        :return: Estimated lambda coefficient.
        """

        # Train regression branch only
        model.compile(optimizer=tf.keras.optimizers.Adam(learning_rate=learning_rate), loss={'regression_head': 'mse'})
        history_reg = model.fit(X_train, {'regression_head': y_train},
                                sample_weight=sample_weights,
                                epochs=n_epochs,
                                batch_size=batch_size,
                                validation_data=(X_val, {'regression_head': y_val}, sample_val_weights))

        reg_losses = history_reg.history['val_loss']

        # Train decoder branch only
        model.compile(optimizer=tf.keras.optimizers.Adam(learning_rate=learning_rate), loss={'decoder_head': 'mse'})
        history_dec = model.fit(X_train, {'decoder_head': X_train},
                                sample_weight=sample_weights,
                                epochs=n_epochs,
                                batch_size=batch_size,
                                validation_data=(X_val, {'decoder_head': X_val}, sample_val_weights))

        dec_losses = history_dec.history['val_loss']

        # Calculate lambda as the sum of the ratios
        ratios = [r / d for r, d in zip(reg_losses, dec_losses)]
        lambda_coef = np.mean(ratios)

        return lambda_coef

    def train_reg_ae_heads(self, model: Model,
                           X_train: ndarray,
                           y_train: ndarray,
                           X_val: ndarray,
                           y_val: ndarray,
                           sample_weights: Optional[ndarray] = None,
                           sample_val_weights: Optional[ndarray] = None,
                           learning_rate: float = 1e-3,
                           epochs: int = 100,
                           batch_size: int = 32,
                           patience: int = 9,
                           save_tag=None) -> callbacks.History:
        """
        Train a neural network model focusing on the regression and autoencoder output.
        Includes reweighting for balancing the loss and saves the model weights.

        :param model: The neural network model.
        :param X_train: Training features.
        :param y_train: Training labels.
        :param X_val: Validation features.
        :param y_val: Validation labels.
        :param sample_weights: Sample weights for training set.
        :param sample_val_weights: Sample weights for validation set.
        :param learning_rate: Learning rate for Adam optimizer.
        :param epochs: Number of epochs.
        :param batch_size: Batch size.
        :param patience: Number of epochs for early stopping.
        :param save_tag: Tag for saving model weights and plots.
        :return: Training history.
        """

        epochs_for_estimation = 25

        lambda_coef = self.estimate_lambda_coef(model, X_train, y_train, X_val, y_val,
                                                sample_weights, sample_val_weights,
                                                learning_rate, epochs_for_estimation, batch_size)

        print(f"Lambda coefficient found: {lambda_coef}")

        # Setup TensorBoard
        log_dir = "logs/fit/" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        tensorboard_cb = callbacks.TensorBoard(log_dir=log_dir, histogram_freq=1)
        print("Run the command line:\n tensorboard --logdir logs/fit")

        # Early stopping callback
        early_stopping_cb = callbacks.EarlyStopping(monitor='val_loss', patience=patience, restore_best_weights=True)

        # Model checkpointing
        checkpoint_cb = callbacks.ModelCheckpoint(f"model_weights_ae_{str(save_tag)}.h5", save_weights_only=True)

        # Compile the model
        model.compile(optimizer=tf.keras.optimizers.Adam(learning_rate=learning_rate),
                      loss={'regression_head': 'mse', 'decoder_head': 'mse'},
                      loss_weights={'regression_head': 1.0, 'decoder_head': lambda_coef})

        # Prepare data dictionary
        y_dict = {'regression_head': y_train, 'decoder_head': X_train}
        val_y_dict = {'regression_head': y_val, 'decoder_head': X_val}

        # Train the model
        history = model.fit(X_train, y_dict,
                            sample_weight=sample_weights,
                            epochs=epochs,
                            batch_size=batch_size,
                            validation_data=(X_val, val_y_dict, sample_val_weights),
                            callbacks=[tensorboard_cb, early_stopping_cb, checkpoint_cb])

        # Find the best epoch from early stopping
        best_epoch = np.argmin(history.history['val_loss']) + 1

        # Plot training and validation loss
        plt.plot(history.history['loss'], label='Training Loss')
        plt.plot(history.history['val_loss'], label='Validation Loss')
        plt.xlabel('Epoch')
        plt.ylabel('Loss')
        plt.title('Training and Validation Loss Over Epochs')
        plt.legend()
        file_path = f"training_ae_plot_{str(save_tag)}.png"
        plt.savefig(file_path)
        plt.close()

        # Combine training and validation data for final training
        X_full = np.concatenate([X_train, X_val], axis=0)
        y_full = np.concatenate([y_train, y_val], axis=0)

        # Combine sample weights if provided
        if sample_weights is not None and sample_val_weights is not None:
            full_sample_weights = np.concatenate([sample_weights, sample_val_weights], axis=0)
        else:
            full_sample_weights = None

        # Retrain the model to the best epoch using combined data
        model.fit(X_full, {'regression_head': y_full, 'decoder_head': X_full},
                  sample_weight=full_sample_weights,
                  epochs=best_epoch,
                  batch_size=batch_size,
                  callbacks=[tensorboard_cb, checkpoint_cb])

        # Save the extended model weights
        model.save_weights(f"extended_model_weights_ae_{str(save_tag)}.h5")

        return history

    def plot_model(self, model: Model, name: str) -> None:
        """
        Plot the model architecture and save the figure.
        :param name: name of the file
        :param model: The model to plot.
        :return: None
        """
        tf.keras.utils.plot_model(model, to_file=f'./{name}.png', show_shapes=True, show_layer_names=True)

    def zdist(self, vec1: Tensor, vec2: Tensor) -> float:
        """
        Computes the squared L2 norm distance between two input feature vectors.

        :param vec1: The first input feature vector.
        :param vec2: The second input feature vector.
        :return: The squared L2 norm distance.
        """
        return tf.reduce_sum(tf.square(vec1 - vec2))

    def ydist(self, val1: float, val2: float) -> float:
        """
        Computes the squared distance between two label values.

        :param val1: The first label value.
        :param val2: The second label value.
        :return: The squared distance.
        """
        return (val1 - val2) ** 2

    def error(self, z1: Tensor, z2: Tensor, label1: float, label2: float) -> float:
        """
        Computes the error between the zdist of two input predicted z values and their ydist.
        Range of the error is [0, 8].

        :param z1: The predicted z value for the first input sample.
        :param z2: The predicted z value for the second input sample.
        :param label1: The label of the first input sample.
        :param label2: The label of the second input sample.
        :return: The squared difference between the zdist and ydist.
        """
        squared_difference = .5 * (self.zdist(z1, z2) - self.ydist(label1, label2)) ** 2
        # added multiplication by .5 to reduce the error range to 0-8
        return tf.reduce_sum(squared_difference)

    def error_vectorized(self, z1: tf.Tensor, z2: tf.Tensor, label1: tf.Tensor, label2: tf.Tensor) -> tf.Tensor:
        """
        Vectorized function to compute the error between the zdist of two batches of input predicted z values
        and their ydist. Range of the error is [0, 8].

        :param z1: A tensor containing the predicted z values for the first batch of input samples.
        :param z2: A tensor containing the predicted z values for the second batch of input samples.
        :param label1: A tensor containing the labels of the first batch of input samples.
        :param label2: A tensor containing the labels of the second batch of input samples.
        :return: A tensor containing the squared differences between the zdist and ydist for each pair.
        """
        z_distance = tf.reduce_sum(tf.square(z1 - z2), axis=-1)
        y_distance = tf.square(label1 - label2)
        squared_difference = 0.5 * tf.square(z_distance - y_distance)

        return squared_difference

    def repr_loss_dl(self, y_true, z_pred, sample_weights=None, reduction=tf.keras.losses.Reduction.NONE):
        """
        Computes the weighted loss for a batch of predicted features and their labels.

        :param y_true: A batch of true label values, shape of [batch_size, 1].
        :param z_pred: A batch of predicted Z values, shape of [batch_size, 2].
        :param sample_weights: A batch of sample weights, shape of [batch_size, 1].
        :param reduction: The type of reduction to apply to the loss.
        :return: The weighted average error for all unique combinations of the samples in the batch.
        """
        int_batch_size = tf.shape(z_pred)[0]
        batch_size = tf.cast(int_batch_size, dtype=tf.float32)
        total_error = tf.constant(0.0, dtype=tf.float32)

        # Initialize counter for sample_weights
        weight_idx = 0

        # Loop through all unique pairs of samples in the batch
        for i in tf.range(int_batch_size):
            for j in tf.range(i + 1, int_batch_size):
                z1, z2 = z_pred[i], z_pred[j]
                label1, label2 = y_true[i], y_true[j]
                err = self.error(z1, z2, label1, label2)  # Assuming `error` is defined elsewhere in your code

                # Apply sample weights if provided
                if sample_weights is not None:
                    weight = sample_weights[weight_idx]  # Get the weight for this pair
                    weighted_err = err * weight
                    weight_idx += 1  # Move to the next weight
                else:
                    weighted_err = err

                total_error += tf.cast(weighted_err, dtype=tf.float32)

        if reduction == tf.keras.losses.Reduction.SUM:
            return total_error  # Total loss
        elif reduction == tf.keras.losses.Reduction.NONE:
            denom = tf.cast(batch_size * (batch_size - 1) / 2 + 1e-9, dtype=tf.float32)
            return total_error / denom  # Average loss
        else:
            raise ValueError(f"Unsupported reduction type: {reduction}.")

    def repr_loss(self, y_true, z_pred, reduction=tf.keras.losses.Reduction.NONE):
        """
        Computes the loss for a batch of predicted features and their labels.
        verified!

        :param y_true: A batch of true label values, shape of [batch_size, 1].
        :param z_pred: A batch of predicted Z values, shape of [batch_size, 2].
        :param reduction: The type of reduction to apply to the loss.
        :return: The average error for all unique combinations of the samples in the batch.
        """
        int_batch_size = tf.shape(z_pred)[0]
        batch_size = tf.cast(int_batch_size, dtype=tf.float32)
        total_error = tf.constant(0.0, dtype=tf.float32)

        # Loop through all unique pairs of samples in the batch
        for i in tf.range(int_batch_size):
            for j in tf.range(i + 1, int_batch_size):
                z1, z2 = z_pred[i], z_pred[j]
                # tf.print(z1, z2, sep=', ', end='\n')
                label1, label2 = y_true[i], y_true[j]
                # tf.print(label1, label2, sep=', ', end='\n')
                err = self.error(z1, z2, label1, label2)
                # tf.print(err, end='\n\n')
                total_error += tf.cast(err, dtype=tf.float32)

        # tf.print(total_error)

        if reduction == tf.keras.losses.Reduction.SUM:
            return total_error  # total loss
        elif reduction == tf.keras.losses.Reduction.NONE:
            denom = tf.cast(batch_size * (batch_size - 1) / 2 + 1e-9, dtype=tf.float32)
            # tf.print(denom)
            return total_error / denom  # average loss
        else:
            raise ValueError(f"Unsupported reduction type: {reduction}.")

    # def repr_loss_fast(self, y_true, z_pred, reduction=tf.keras.losses.Reduction.NONE):
    #     """
    #     Computes the loss for a batch of predicted features and their labels.
    #      TODO: Leads to wrong losses, how to fix it?
    #     :param y_true: A batch of true label values, shape of [batch_size, 1].
    #     :param z_pred: A batch of predicted Z values, shape of [batch_size, 2].
    #     :param reduction: The type of reduction to apply to the loss.
    #     :return: The average error for all unique combinations of the samples in the batch.
    #     """
    #     batch_size = tf.shape(z_pred)[0]
    #     denom = tf.cast(batch_size * (batch_size - 1) / 2, dtype=tf.float32)
    #
    #     # Compute all pairs of errors at once
    #     # We expand dimensions to prepare for broadcasting
    #     z1 = tf.expand_dims(z_pred, 1)
    #     z2 = tf.expand_dims(z_pred, 0)
    #     label1 = tf.expand_dims(y_true, 1)
    #     label2 = tf.expand_dims(y_true, 0)
    #
    #     # Compute the pairwise errors using the 'self.error' function
    #     err_matrix = self.error_vectorized(z1, z2, label1, label2)
    #
    #     mask_upper_triangle = tf.linalg.band_part(tf.ones_like(err_matrix), 0, -1)  # Upper triangular matrix of ones
    #     mask_no_diag = mask_upper_triangle - tf.eye(tf.shape(err_matrix)[0])  # Remove diagonal
    #     total_error = tf.reduce_sum(err_matrix * mask_no_diag)
    #
    #     if reduction == tf.keras.losses.Reduction.SUM:
    #         return total_error  # total loss
    #     elif reduction == tf.keras.losses.Reduction.NONE:
    #         return total_error / (denom + 1e-9)  # average loss
    #     else:
    #         raise ValueError(f"Unsupported reduction type: {reduction}.")


class NormalizeLayer(layers.Layer):
    def __init__(self, epsilon: float = 1e-9, **kwargs):
        """
        Initialization for the NormalizeLayer.

        :param epsilon: A small constant to prevent division by zero during normalization. Default is 1e-9.
        :param kwargs: Additional keyword arguments for the parent class.
        """
        self.epsilon = epsilon
        super(NormalizeLayer, self).__init__(**kwargs)

    def call(self, reprs: Tensor) -> Tensor:
        """
        Forward pass for the NormalizeLayer.

        :param reprs: Input tensor of shape [batch_size, ...].
        :return: Normalized input tensor of the same shape as inputs.
        """
        norm = tf.norm(reprs, axis=1, keepdims=True) + self.epsilon
        return reprs / norm

    def get_config(self) -> dict:
        """
        Returns the config of the layer. Contains the layer's configuration as a dict,
        including the `epsilon` parameter and the configurations of the parent class.

        :return: A dict containing the layer's configuration.
        """
        config = super().get_config()
        config.update({
            "epsilon": self.epsilon,
        })
        return config


# def map_to_1D_idx(i, j, n):
#     """Map the 2D index (i, j) of an n x n upper triangular matrix to the
#     corresponding 1D index of its flattened form.
#     :param i: The row index.
#     :param j: The column index.
#     :param n: The number of rows in the upper triangular matrix.
#     :return: The 1D index of the flattened form.
#     """
#     return n * i + j - ((i + 1) * (i + 2)) // 2

# Helper function to map 2D indices to 1D indices (assuming it's defined elsewhere in your code)
def map_to_1D_idx(i, j, n):
    return n * i + j
