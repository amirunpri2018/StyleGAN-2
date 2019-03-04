import tensorflow as tf
import numpy as np
from ops import *


def log(x, base): return tf.log(x) / tf.log(base)


def lerp(a, b, t): return t * a + (1. - t) * b


class PGGAN(object):

    def __init__(self, min_resolution, max_resolution, min_channels, max_channels):

        self.min_resolution = np.asanyarray(min_resolution)
        self.max_resolution = np.asanyarray(max_resolution)
        self.min_channels = min_channels
        self.max_channels = max_channels

        def log2(x): return 0 if (x == 1).all() else 1 + log2(x >> 1)

        self.min_depth = log2(self.min_resolution // self.min_resolution)
        self.max_depth = log2(self.max_resolution // self.min_resolution)

    def generator(self, latents, labels, training, progress, name="ganerator", reuse=None):

        def resolution(depth): return self.min_resolution << depth

        def channels(depth): return min(self.max_channels, self.min_channels << (self.max_depth - depth))

        def conv_block(inputs, depth, reuse=tf.AUTO_REUSE):
            with tf.variable_scope("conv_block_{}x{}".format(*resolution(depth)), reuse=reuse):
                if depth == self.min_depth:
                    inputs = tf.reshape(inputs, [-1, inputs.shape[1], 1, 1])
                    inputs = pixel_norm(inputs)
                    with tf.variable_scope("conv_upscale"):
                        inputs = conv2d_transpose(
                            inputs=inputs,
                            filters=channels(depth),
                            kernel_size=resolution(depth).tolist(),
                            strides=resolution(depth).tolist()
                        )
                        inputs = tf.nn.leaky_relu(inputs)
                        inputs = pixel_norm(inputs)
                    with tf.variable_scope("conv"):
                        inputs = conv2d(
                            inputs=inputs,
                            filters=channels(depth),
                            kernel_size=[3, 3]
                        )
                        inputs = tf.nn.leaky_relu(inputs)
                        inputs = pixel_norm(inputs)
                else:
                    with tf.variable_scope("conv_upscale"):
                        inputs = conv2d_transpose(
                            inputs=inputs,
                            filters=channels(depth),
                            kernel_size=[3, 3],
                            strides=[2, 2]
                        )
                        inputs = tf.nn.leaky_relu(inputs)
                        inputs = pixel_norm(inputs)
                    with tf.variable_scope("conv"):
                        inputs = conv2d(
                            inputs=inputs,
                            filters=channels(depth),
                            kernel_size=[3, 3]
                        )
                        inputs = tf.nn.leaky_relu(inputs)
                        inputs = pixel_norm(inputs)
                return inputs

        def color_block(inputs, depth, reuse=tf.AUTO_REUSE):
            with tf.variable_scope("color_block_{}x{}".format(*resolution(depth)), reuse=reuse):
                with tf.variable_scope("conv"):
                    inputs = conv2d(
                        inputs=inputs,
                        filters=2,
                        kernel_size=[1, 1],
                        variance_scale=1
                    )
                    inputs = tf.nn.tanh(inputs)
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
            return grow(latents, self.min_depth)

    def discriminator(self, images, labels, training, progress, name="dicriminator", reuse=None):

        def resolution(depth): return self.min_resolution << depth

        def channels(depth): return min(self.max_channels, self.min_channels << (self.max_depth - depth))

        def conv_block(inputs, depth, reuse=tf.AUTO_REUSE):
            with tf.variable_scope("conv_block_{}x{}".format(*resolution(depth)), reuse=reuse):
                if depth == self.min_depth:
                    inputs = batch_stddev(inputs)
                    with tf.variable_scope("conv"):
                        inputs = conv2d(
                            inputs=inputs,
                            filters=channels(depth),
                            kernel_size=[3, 3]
                        )
                        inputs = tf.nn.leaky_relu(inputs)
                    with tf.variable_scope("conv_downscale"):
                        inputs = conv2d(
                            inputs=inputs,
                            filters=channels(depth - 1),
                            kernel_size=resolution(depth).tolist(),
                            strides=resolution(depth).tolist()
                        )
                        inputs = tf.nn.leaky_relu(inputs)
                    inputs = tf.reshape(inputs, [-1, inputs.shape[1]])
                    with tf.variable_scope("logits"):
                        logits = dense(
                            inputs=inputs,
                            units=1
                        )
                    with tf.variable_scope("projection"):
                        inputs = logits + projection(
                            inputs=inputs,
                            labels=labels
                        )
                else:
                    with tf.variable_scope("conv"):
                        inputs = conv2d(
                            inputs=inputs,
                            filters=channels(depth),
                            kernel_size=[3, 3]
                        )
                        inputs = tf.nn.leaky_relu(inputs)
                    with tf.variable_scope("conv_downscale"):
                        inputs = conv2d(
                            inputs=inputs,
                            filters=channels(depth - 1),
                            kernel_size=[3, 3],
                            strides=[2, 2]
                        )
                        inputs = tf.nn.leaky_relu(inputs)
                return inputs

        def color_block(inputs, depth, reuse=tf.AUTO_REUSE):
            with tf.variable_scope("color_block_{}x{}".format(*resolution(depth)), reuse=reuse):
                with tf.variable_scope("conv"):
                    inputs = conv2d(
                        inputs=inputs,
                        filters=channels(depth),
                        kernel_size=[1, 1]
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
