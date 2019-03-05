import tensorflow as tf
import numpy as np
from ops import *


def log(x, base): return tf.log(x) / tf.log(base)


def lerp(a, b, t): return t * a + (1. - t) * b


class StyleGAN(object):

    def __init__(self, min_resolution, max_resolution, min_channels, max_channels, mapping_layers):

        self.min_resolution = np.asanyarray(min_resolution)
        self.max_resolution = np.asanyarray(max_resolution)
        self.min_channels = min_channels
        self.max_channels = max_channels
        self.mapping_layers = mapping_layers

        def log2(x): return 0 if (x == 1).all() else 1 + log2(x >> 1)

        self.min_depth = log2(self.min_resolution // self.min_resolution)
        self.max_depth = log2(self.max_resolution // self.min_resolution)

    def generator(self, latents, labels, training, progress, name="ganerator", reuse=None):

        def resolution(depth): return self.min_resolution << depth

        def channels(depth): return min(self.max_channels, self.min_channels << (self.max_depth - depth))

        def conv_block(inputs, depth, reuse=tf.AUTO_REUSE):
            with tf.variable_scope("conv_block_{}x{}".format(*resolution(depth)), reuse=reuse):
                if depth == self.min_depth:
                    # learned constant input
                    with tf.variable_scope("const"):
                        const = tf.get_variable(
                            name="const",
                            shape=[1, channels(depth), *resolution(depth)]
                        )
                        inputs = tf.tile(const, [tf.shape(inputs)[0], 1, 1, 1])
                        # apply learned per-channel scaling factors to the noise input
                        with tf.variable_scope("noise"):
                            inputs = apply_noise(inputs)
                        inputs = tf.nn.leaky_relu(inputs)
                        # inputs = pixel_norm(inputs)
                        # adaptive instance normalization (AdaIN)
                        with tf.variable_scope("adaptive_instance_norm"):
                            inputs = adaptive_instance_norm(
                                inputs=inputs,
                                latents=latents,
                                use_bias=True,
                                variance_scale=2,
                                scale_weight=True
                            )
                    with tf.variable_scope("conv"):
                        inputs = conv2d(
                            inputs=inputs,
                            filters=channels(depth),
                            kernel_size=[3, 3],
                            use_bias=True,
                            variance_scale=2,
                            scale_weight=True
                        )
                        # apply learned per-channel scaling factors to the noise input
                        with tf.variable_scope("noise"):
                            inputs = apply_noise(inputs)
                        inputs = tf.nn.leaky_relu(inputs)
                        # inputs = pixel_norm(inputs)
                        # adaptive instance normalization (AdaIN)
                        with tf.variable_scope("adaptive_instance_norm"):
                            inputs = adaptive_instance_norm(
                                inputs=inputs,
                                latents=latents,
                                use_bias=True,
                                variance_scale=2,
                                scale_weight=True
                            )
                else:
                    with tf.variable_scope("upscale_conv"):
                        inputs = conv2d_transpose(
                            inputs=inputs,
                            filters=channels(depth),
                            kernel_size=[3, 3],
                            strides=[2, 2],
                            use_bias=True,
                            variance_scale=2,
                            scale_weight=True
                        )
                        # apply learned per-channel scaling factors to the noise input
                        with tf.variable_scope("noise"):
                            inputs = apply_noise(inputs)
                        inputs = tf.nn.leaky_relu(inputs)
                        # inputs = pixel_norm(inputs)
                        # adaptive instance normalization (AdaIN)
                        with tf.variable_scope("adaptive_instance_norm"):
                            inputs = adaptive_instance_norm(
                                inputs=inputs,
                                latents=latents,
                                use_bias=True,
                                variance_scale=2,
                                scale_weight=True
                            )
                    with tf.variable_scope("conv"):
                        inputs = conv2d(
                            inputs=inputs,
                            filters=channels(depth),
                            kernel_size=[3, 3],
                            use_bias=True,
                            variance_scale=2,
                            scale_weight=True
                        )
                        # apply learned per-channel scaling factors to the noise input
                        with tf.variable_scope("noise"):
                            inputs = apply_noise(inputs)
                        inputs = tf.nn.leaky_relu(inputs)
                        # inputs = pixel_norm(inputs)
                        # adaptive instance normalization (AdaIN)
                        with tf.variable_scope("adaptive_instance_norm"):
                            inputs = adaptive_instance_norm(
                                inputs=inputs,
                                latents=latents,
                                use_bias=True,
                                variance_scale=2,
                                scale_weight=True
                            )
                return inputs

        def color_block(inputs, depth, reuse=tf.AUTO_REUSE):
            with tf.variable_scope("color_block_{}x{}".format(*resolution(depth)), reuse=reuse):
                with tf.variable_scope("conv"):
                    inputs = conv2d(
                        inputs=inputs,
                        filters=3,
                        kernel_size=[1, 1],
                        use_bias=True,
                        variance_scale=1,
                        scale_weight=True
                    )
                    # linear activation
                    # inputs = tf.nn.tanh(inputs)
                return inputs

        def grow(feature_maps, depth):

            def high_resolution_images():
                return grow(conv_block(feature_maps, depth), depth + 1)

            def middle_resolution_images():
                return upscale2d(
                    inputs=color_block(conv_block(feature_maps, depth), depth),
                    factors=resolution(self.max_depth) // resolution(depth)
                )

            def low_resolution_images():
                return upscale2d(
                    inputs=color_block(feature_maps, depth - 1),
                    factors=resolution(self.max_depth) // resolution(depth - 1)
                )

            if depth == self.min_depth:
                images = tf.cond(
                    pred=tf.greater(growing_depth, depth),
                    true_fn=high_resolution_images,
                    false_fn=middle_resolution_images
                )
            elif depth == self.max_depth:
                images = tf.cond(
                    pred=tf.greater(growing_depth, depth),
                    true_fn=middle_resolution_images,
                    false_fn=lambda: lerp(
                        a=low_resolution_images(),
                        b=middle_resolution_images(),
                        t=depth - growing_depth
                    )
                )
            else:
                images = tf.cond(
                    pred=tf.greater(growing_depth, depth),
                    true_fn=high_resolution_images,
                    false_fn=lambda: lerp(
                        a=low_resolution_images(),
                        b=middle_resolution_images(),
                        t=depth - growing_depth
                    )
                )
            return images

        with tf.variable_scope(name, reuse=reuse):

            growing_depth = log((1 << self.min_depth) + progress * ((1 << (self.max_depth + 1)) - (1 << self.min_depth)), 2.)

            # label embedding
            labels = embed(
                inputs=labels,
                units=latents.shape[1],
                variance_scale=1,
                scale_weight=True
            )
            latents = tf.concat([latents, labels], axis=1)
            latents = pixel_norm(latents)

            # mapping network
            for i in range(self.mapping_layers):
                with tf.variable_scope("mapping_layer_{}".format(i)):
                    latents = dense(
                        inputs=latents,
                        units=latents.shape[1],
                        use_bias=True,
                        variance_scale=2,
                        scale_weight=True
                    )
                    latents = tf.nn.leaky_relu(latents)

            return grow(latents, self.min_depth)

    def discriminator(self, images, labels, training, progress, name="dicriminator", reuse=None):

        def resolution(depth): return self.min_resolution << depth

        def channels(depth): return min(self.max_channels, self.min_channels << (self.max_depth - depth))

        def conv_block(inputs, depth, reuse=tf.AUTO_REUSE):
            with tf.variable_scope("conv_block_{}x{}".format(*resolution(depth)), reuse=reuse):
                if depth == self.min_depth:
                    inputs = tf.concat([inputs, batch_stddev(inputs)], axis=1)
                    with tf.variable_scope("conv"):
                        inputs = conv2d(
                            inputs=inputs,
                            filters=channels(depth),
                            kernel_size=[3, 3],
                            use_bias=True,
                            variance_scale=2,
                            scale_weight=True
                        )
                        inputs = tf.nn.leaky_relu(inputs)
                    with tf.variable_scope("dense"):
                        inputs = tf.layers.flatten(inputs)
                        inputs = dense(
                            inputs=inputs,
                            units=channels(depth - 1),
                            use_bias=True,
                            variance_scale=2,
                            scale_weight=True
                        )
                        inputs = tf.nn.leaky_relu(inputs)
                    with tf.variable_scope("logits"):
                        inputs = dense(
                            inputs=inputs,
                            units=labels.shape[1],
                            use_bias=True,
                            variance_scale=1,
                            scale_weight=True
                        )
                        # label conditioning from
                        # [Which Training Methods for GANs do actually Converge?]
                        # (https://arxiv.org/pdf/1801.04406.pdf)
                        inputs *= tf.cast(labels, tf.float32)
                        inputs = tf.reduce_sum(
                            input_tensor=inputs,
                            axis=1,
                            keepdims=True
                        )

                else:
                    with tf.variable_scope("conv"):
                        inputs = conv2d(
                            inputs=inputs,
                            filters=channels(depth),
                            kernel_size=[3, 3],
                            use_bias=True,
                            variance_scale=2,
                            scale_weight=True
                        )
                        inputs = tf.nn.leaky_relu(inputs)
                    with tf.variable_scope("conv_downscale"):
                        inputs = conv2d(
                            inputs=inputs,
                            filters=channels(depth - 1),
                            kernel_size=[3, 3],
                            strides=[2, 2],
                            use_bias=True,
                            variance_scale=2,
                            scale_weight=True
                        )
                        inputs = tf.nn.leaky_relu(inputs)
                return inputs

        def color_block(inputs, depth, reuse=tf.AUTO_REUSE):
            with tf.variable_scope("color_block_{}x{}".format(*resolution(depth)), reuse=reuse):
                with tf.variable_scope("conv"):
                    inputs = conv2d(
                        inputs=inputs,
                        filters=channels(depth),
                        kernel_size=[1, 1],
                        use_bias=True,
                        variance_scale=2,
                        scale_weight=True
                    )
                    inputs = tf.nn.leaky_relu(inputs)
                return inputs

        def grow(images, depth):

            def high_resolution_feature_maps():
                return conv_block(grow(images, depth + 1), depth)

            def middle_resolution_feature_maps():
                return conv_block(color_block(downscale2d(
                    inputs=images,
                    factors=resolution(self.max_depth) // resolution(depth)
                ), depth), depth)

            def low_resolution_feature_maps():
                return color_block(downscale2d(
                    inputs=images,
                    factors=resolution(self.max_depth) // resolution(depth - 1)
                ), depth - 1)

            if depth == self.min_depth:
                feature_maps = tf.cond(
                    pred=tf.greater(growing_depth, depth),
                    true_fn=high_resolution_feature_maps,
                    false_fn=middle_resolution_feature_maps
                )
            elif depth == self.max_depth:
                feature_maps = tf.cond(
                    pred=tf.greater(growing_depth, depth),
                    true_fn=middle_resolution_feature_maps,
                    false_fn=lambda: lerp(
                        a=low_resolution_feature_maps(),
                        b=middle_resolution_feature_maps(),
                        t=depth - growing_depth
                    )
                )
            else:
                feature_maps = tf.cond(
                    pred=tf.greater(growing_depth, depth),
                    true_fn=high_resolution_feature_maps,
                    false_fn=lambda: lerp(
                        a=low_resolution_feature_maps(),
                        b=middle_resolution_feature_maps(),
                        t=depth - growing_depth
                    )
                )
            return feature_maps

        with tf.variable_scope(name, reuse=reuse):

            growing_depth = log((1 << self.min_depth) + progress * ((1 << (self.max_depth + 1)) - (1 << self.min_depth)), 2.)

            return grow(images, self.min_depth)
