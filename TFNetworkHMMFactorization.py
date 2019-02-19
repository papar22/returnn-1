import tensorflow as tf
from TFNetworkLayer import _ConcatInputLayer, get_concat_sources_data_template
from TFUtil import Data


class HMMFactorization(_ConcatInputLayer):

  layer_class = "hmm_factorization"

  def __init__(self, attention_weights, base_encoder_transformed, prev_state, prev_outputs, n_out, debug=False,
               threshold=None, transpose_and_average_att_weights=False, top_k=None, non_probabilistic=False, **kwargs):
    """
    HMM factorization as described in Parnia Bahar's paper.
    Out of rnn loop usage.
    Please refer to the demos to see the layer in use.
    :param LayerBase attention_weights: Attention weights of shape [I, J, B, 1]
    :param LayerBase base_encoder_transformed: Encoder, inner most dimension transformed to a constant size
    'intermediate_size'. Tensor of shape [J, B, intermediate_size]
    :param LayerBase prev_state: Previous state data, with the innermost dimension set to a constant size
    'intermediate_size'. Tensor of shape [I, B, intermediate_size].
    :param LayerBase prev_outputs: Previous output data with the innermost dimension set to a constant size
    'intermediate_size'. Tensor of shape [I, B, intermediate_size]
    :param bool debug: True/False, whether to print debug info or not
    :param float|None threshold: (float, >0), if not set to 'none', all attention values below this threshold will be
    set to 0. Slightly improves speed.
    :param bool transpose_and_average_att_weights: Set to True if using Transformer architecture. So, if
    attention_weights are of shape [J, B, H, I] with H being the amount of heads in the architecture. We will then
    average out over the heads to get the final attention values used.
    :param int n_out: Size of output dim (usually not set manually)
    TODO top_k documentation
    :param kwargs:
    """
    # TODO: TEST IT FOR DECODING!
    super(HMMFactorization, self).__init__(**kwargs)

    in_loop = True if len(prev_state.output.shape) == 1 else False

    # # Get data
    if in_loop is False:
      self.attention_weights = attention_weights.output.get_placeholder_as_time_major() # [I, J, B, 1]
      self.base_encoder_transformed = base_encoder_transformed.output.get_placeholder_as_time_major() # [B, J, f]
      self.prev_state = prev_state.output.get_placeholder_as_time_major() # [I, B, f]
      self.prev_outputs = prev_outputs.output.get_placeholder_as_time_major() # [I, B, f]
    else:
      self.attention_weights = attention_weights.output.get_placeholder_as_batch_major()
      self.base_encoder_transformed = base_encoder_transformed.output.get_placeholder_as_batch_major()  # [B, J, f]
      self.prev_state = prev_state.output.get_placeholder_as_batch_major()  # [B, f]
      self.prev_outputs = prev_outputs.output.get_placeholder_as_batch_major()  # [B, f]



    if debug:
      self.attention_weights = tf.Print(self.attention_weights, [tf.shape(self.attention_weights)],
                                        message='Attention weight shape: ', summarize=100)

    if debug:
      self.base_encoder_transformed = tf.Print(self.base_encoder_transformed, [tf.shape(self.base_encoder_transformed),
                                                                               tf.shape(self.prev_state),
                                                                               tf.shape(self.prev_outputs)],
                                               message='Shapes of base encoder, prev_state and prev_outputs pre shaping: ',
                                               summarize=100)

    # Transpose and average out attention weights (for when we use transformer architecture)
    if transpose_and_average_att_weights is True:

      if in_loop is False:
        # attention_weights is [J, B, H, I]
        self.attention_weights = tf.transpose(self.attention_weights, perm=[3, 0, 1, 2])  # Now it is [I, J, B, H]
        self.attention_weights = tf.reduce_mean(self.attention_weights, keep_dims=True, axis=3)  # Now [I, J, B, 1]
      else:
        # attention_weights is [J, B, H, 1?]
        self.attention_weights = tf.squeeze(self.attention_weights, axis=3)
        self.attention_weights = tf.reduce_mean(self.attention_weights, keep_dims=True, axis=2)
        self.attention_weights = tf.transpose(self.attention_weights, perm=[1, 0, 2])  # Now it is [J, B, 1]

      if debug:
        self.attention_weights = tf.Print(self.attention_weights, [tf.shape(self.attention_weights)],
                                          message='Attention weight shape after transposing and avg: ', summarize=100)
    else:
      if in_loop is True:
        # Edge case of attention weights
        self.attention_weights = tf.transpose(self.attention_weights, perm=[1, 0, 2])  # Now [J, B, 1]
        if debug:
          self.attention_weights = tf.Print(self.attention_weights, [tf.shape(self.attention_weights)],
                                            message='Attention weight shape after transposing: ', summarize=100)


    # Get data
    #attention_weights_shape = tf.shape(self.attention_weights)
    if in_loop is False:
      attention_weights_shape = tf.shape(self.attention_weights) # [I, J, B, 1]
      time_i = attention_weights_shape[0]
      batch_size = attention_weights_shape[2]
      time_j = attention_weights_shape[1]
    else:
      attention_weights_shape = tf.shape(self.attention_weights) # [J, B, 1]
      batch_size = attention_weights_shape[1]
      time_j = attention_weights_shape[0]

    # Use only top_k from self.attention_weights
    if top_k is not None:

      if in_loop is False:
        temp_attention_weights = tf.transpose(self.attention_weights, perm=[0, 2, 3, 1])  # Now [I, B, 1, J]
      else:
        temp_attention_weights = tf.transpose(self.attention_weights, perm=[1, 2, 0])  # Now [B, 1, J]
      temp_k = tf.minimum(top_k, time_j)
      top_values, top_indices = tf.nn.top_k(temp_attention_weights, k=temp_k) # top_values and indices [(I,) B, 1, top_k]

      # TODO: Fix self.base_encoder_transformed to only contain top_k

      if in_loop is False:
        self.attention_weights = tf.transpose(top_values, perm=[0, 3, 1, 2])  # Now [I, J=top_k, B, 1]
      else:
        self.attention_weights = tf.transpose(top_values, perm=[2, 0, 1])  # Now [J=top_k, B, 1]

      if debug:
        self.attention_weights = tf.Print(self.attention_weights, [tf.shape(self.attention_weights)],
                                          message='Top K Attention weight shape: ', summarize=100)

    # Convert base_encoder_transformed, prev_state and prev_outputs to correct shape
    if in_loop is False:
      self.base_encoder_transformed = tf.tile(tf.expand_dims(self.base_encoder_transformed, axis=0),
                                              [time_i, 1, 1, 1])  # [I, J, B, f]
      if top_k is not None:
        self.prev_state = tf.tile(tf.expand_dims(self.prev_state, axis=1),
                                [1, temp_k, 1, 1])  # [I, J=top_k, B, f]

        self.prev_outputs = tf.tile(tf.expand_dims(self.prev_outputs, axis=1),
                                  [1, temp_k, 1, 1])  # [I, J=top_k, B, f]
      else:
        self.prev_state = tf.tile(tf.expand_dims(self.prev_state, axis=1),
                                    [1, time_j, 1, 1])  # [I, J, B, f]
        self.prev_outputs = tf.tile(tf.expand_dims(self.prev_outputs, axis=1),
                                  [1, time_j, 1, 1])  # [I, J, B, f]
    else:
      self.base_encoder_transformed = tf.transpose(self.base_encoder_transformed,
                                                   perm=[1, 0, 2])  # [J, B, f]
      if top_k is not None:
        self.prev_state = tf.tile(tf.expand_dims(self.prev_state, axis=0),
                                [temp_k, 1, 1])  # [J=top_k, B, f]

        self.prev_outputs = tf.tile(tf.expand_dims(self.prev_outputs, axis=0),
                                  [temp_k, 1, 1])  # [J=top_k, B, f]
      else:
        self.prev_state = tf.tile(tf.expand_dims(self.prev_state, axis=0),
                                    [time_j, 1, 1])  # [J, B, f]
        self.prev_outputs = tf.tile(tf.expand_dims(self.prev_outputs, axis=0),
                                  [time_j, 1, 1])  # [J, B, f]

    # Fix self.base_encoder_transformed if in top_k
    if top_k is not None:
      if in_loop is False:
        self.base_encoder_transformed = tf.transpose(self.base_encoder_transformed,
                                                     perm=[0, 2, 1, 3])  # Now [I, B, J, f]
        top_indices = tf.squeeze(top_indices, axis=2)
        ii, jj, _ = tf.meshgrid(tf.range(time_i), tf.range(batch_size), tf.range(temp_k), indexing='ij') # [I B k]

        # Stack complete index
        index = tf.stack([ii, jj, top_indices], axis=-1) # [I B k 3]
        # index = tf.Print(index, [tf.shape(index)], message='index shape: ', summarize=100)
      else:
        self.base_encoder_transformed = tf.transpose(self.base_encoder_transformed,
                                                     perm=[1, 0, 2])  # Now [B, J, f]
        top_indices = tf.squeeze(top_indices, axis=1)
        jj, _ = tf.meshgrid(tf.range(batch_size), tf.range(temp_k), indexing='ij')
        # Stack complete index
        index = tf.stack([jj, top_indices], axis=-1)

      # Get the same values again
      self.base_encoder_transformed = tf.gather_nd(self.base_encoder_transformed, index) # Now [I, B, J=k, f]

      if in_loop is False:
        self.base_encoder_transformed = tf.transpose(self.base_encoder_transformed,
                                                     perm=[0, 2, 1, 3])  # [I, J, B, f]
      else:
        self.base_encoder_transformed = tf.transpose(self.base_encoder_transformed,
                                                     perm=[1, 0, 2])  # [J, B, f]

    if debug:
      self.base_encoder_transformed = tf.Print(self.base_encoder_transformed,
                                                 [tf.shape(self.base_encoder_transformed),
                                                  tf.shape(self.prev_state),
                                                  tf.shape(self.prev_outputs)],
                                                 message='Shapes of base encoder, prev_state '
                                                         'and prev_outputs post shaping: ',
                                                 summarize=100)


    # Permutate attention weights correctly
    if in_loop is False:
      self.attention_weights = tf.transpose(self.attention_weights, perm=[0, 2, 3, 1])  # Now [I, B, 1, J]
    else:
      # Before [J, B, 1]
      self.attention_weights = tf.transpose(self.attention_weights, perm=[1, 2, 0])  # Now [B, 1, J]

    if debug:
      self.attention_weights = tf.Print(self.attention_weights, [tf.shape(self.attention_weights)],
                                        message='attention_weights shape transposed: ',
                                        summarize=100)

      self.base_encoder_transformed = tf.Print(self.base_encoder_transformed,
                                               [tf.shape(self.base_encoder_transformed + self.prev_outputs + self.prev_state)],
                                               message='Pre lex logits shape: ', summarize=100)

    # Get logits, now [I, J, B, vocab_size]/[J, B, vocab_size]
    lexicon_logits = tf.layers.dense(self.base_encoder_transformed + self.prev_outputs + self.prev_state,
                                     units=n_out,
                                     activation=None,
                                     use_bias=False)

    if debug:
      lexicon_logits = tf.Print(lexicon_logits, [tf.shape(lexicon_logits)], message='Post lex logits shape: ', summarize=100)

    if in_loop is False:
      lexicon_logits = tf.transpose(lexicon_logits, perm=[0, 2, 1, 3])  # Now [I, B, J, vocab_size]
    else:
      lexicon_logits = tf.transpose(lexicon_logits, perm=[1, 0, 2])  # Now [B, J, vocab_size]

    # Optimization with thresholding
    if threshold is not None:
      # Get mask
      amount_to_debug = 10

      if debug:
        self.attention_weights = tf.Print(self.attention_weights, [self.attention_weights],
                                          message='self.attention_weights: ', summarize=amount_to_debug)

      mask_values_to_keep = self.attention_weights > threshold  # Of shape [I, B, 1, J]

      # Modify mask to be of same shape as lexicon data
      mask_values_to_keep = tf.transpose(mask_values_to_keep, perm=[0, 1, 3, 2])  # Now [I, B, J, 1]
      mask_values_to_keep = tf.tile(mask_values_to_keep, [1, 1, 1, n_out])  # [I, B, J, vocab_size]

      if debug:
        mask_values_to_keep = tf.Print(mask_values_to_keep, [tf.shape(mask_values_to_keep)],
                                       message='mask_values_to_keep shape: ', summarize=100)
        mask_values_to_keep = tf.Print(mask_values_to_keep, [mask_values_to_keep],
                                       message='mask_values_to_keep: ', summarize=amount_to_debug)
        lexicon_logits = tf.Print(lexicon_logits, [lexicon_logits],
                                 message='lexicon_model pre mask: ', summarize=amount_to_debug)

      # Apply mask
      lexicon_logits = tf.where(mask_values_to_keep, lexicon_logits, tf.zeros_like(lexicon_logits))

      if debug:
        lexicon_logits = tf.Print(lexicon_logits, [lexicon_logits],
                                  message='lexicon_model post mask: ', summarize=amount_to_debug)


    if non_probabilistic:
      # Now [I, B, J, vocab_size]/[B, J, vocab_size], Perform softmax on last layer
      lexicon_model = tf.nn.sigmoid(lexicon_logits + 1e-12)
    else:
      lexicon_model = tf.nn.softmax(lexicon_logits)

    if debug:
      lexicon_model = tf.Print(lexicon_model, [tf.shape(lexicon_model)], message='lexicon_model shape: ', summarize=100)

    # in_loop=True   Multiply for final logits, [B, 1, J] x [B, J, vocab_size] ----> [B, 1, vocab]
    # in_loop=False: Multiply for final logits, [I, B, 1, J] x [I, B, J, vocab_size] ----> [I, B, 1, vocab]
    final_output = tf.matmul(self.attention_weights, lexicon_model)

    if debug:
      final_output = tf.Print(final_output, [tf.shape(final_output)], message='final_output shape: ', summarize=100)

    if in_loop is False:
      # Squeeze [I, B, vocab]
      final_output = tf.squeeze(final_output, axis=2)
    else:
      # Squeeze [B, vocab]
      final_output = tf.squeeze(final_output, axis=1)

    if debug:
      final_output = tf.Print(final_output, [tf.shape(final_output)], message='final_output post squeeze shape: ',
                              summarize=100)

    # Set shaping info
    if in_loop is False:
      if transpose_and_average_att_weights is True:
        output_size = self.input_data.size_placeholder[2]
        if debug:
          final_output = tf.Print(final_output, [self.input_data.size_placeholder[2]],
                                  message='Prev output size placeholder: ',
                                  summarize=100)
      else:
        output_size = self.input_data.size_placeholder[0]
        if debug:
          final_output = tf.Print(final_output, [self.input_data.size_placeholder[0]],
                                  message='Prev output size placeholder: ',
                                  summarize=100)

    self.output.placeholder = final_output

    if in_loop is False:
      self.output.size_placeholder = {
        0: output_size
      }
    else:
      self.output.size_placeholder = {}

    if in_loop is False:
      self.output.time_dim_axis = 0
      self.output.batch_dim_axis = 1
    else:
      self.output.batch_dim_axis = 0
      self.output.time_dim_axis = None

    self.output.beam_size = prev_state.output.beam_size

    # Add all trainable params
    with self.var_creation_scope() as scope:
      self._add_all_trainable_params(tf.get_collection(tf.GraphKeys.TRAINABLE_VARIABLES, scope=scope.name))

  def _add_all_trainable_params(self, tf_vars):
    for var in tf_vars:
      self.add_param(param=var, trainable=True, saveable=True)

  @classmethod
  def transform_config_dict(cls, d, network, get_layer):
    d.setdefault("from", [d["attention_weights"]])
    super(HMMFactorization, cls).transform_config_dict(d, network=network, get_layer=get_layer)
    d["attention_weights"] = get_layer(d["attention_weights"])
    d["base_encoder_transformed"] = get_layer(d["base_encoder_transformed"])
    d["prev_state"] = get_layer(d["prev_state"])
    d["prev_outputs"] = get_layer(d["prev_outputs"])

  @classmethod
  def get_out_data_from_opts(cls, attention_weights, prev_state, n_out, out_type=None, sources=(), **kwargs):

    in_loop = True if len(prev_state.output.shape) == 1 else False

    data = attention_weights.output

    if in_loop is False:
      data = data.copy_as_time_major()  # type: Data
      data.shape = (None, n_out)
      data.time_dim_axis = 0
      data.batch_dim_axis = 1
      data.dim = n_out
    else:
      data = data.copy_as_batch_major()  # type: Data
      data.shape = (n_out,)
      data.batch_dim_axis = 0
      data.time_dim_axis = None
      data.dim = n_out
    return data

