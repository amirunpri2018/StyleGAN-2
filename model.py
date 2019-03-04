import tensorflow as tf
import numpy as np
import itertools
import functools
import os


class GANSynth(object):

    def __init__(self, discriminator, generator, real_input_fn, fake_input_fn,
                 hyper_params, name="gan_synth", reuse=None):

        with tf.variable_scope(name, reuse=reuse):
            # =========================================================================================
            self.name = name
            self.hyper_params = hyper_params
            # =========================================================================================
            # parameters
            self.training = tf.placeholder(dtype=tf.bool, shape=[])
            self.total_steps = tf.placeholder(dtype=tf.int32, shape=[])
            self.global_step = tf.Variable(initial_value=0, trainable=False)
            self.progress = tf.cast(self.global_step / self.total_steps, tf.float32)
            # =========================================================================================
            # input_fn for real data and fake data
            self.real_images, self.real_labels = real_input_fn()
            self.fake_latents, self.fake_labels = fake_input_fn()
            # =========================================================================================
            # generated fake data
            self.fake_images = generator(
                latents=self.fake_latents,
                labels=self.fake_labels,
                training=self.training,
                progress=self.progress,
                name="generator"
            )
            # =========================================================================================
            # logits for real data and fake data
            self.real_logits = discriminator(
                images=self.real_images,
                labels=self.real_labels,
                training=self.training,
                progress=self.progress,
                name="discriminator"
            )
            self.fake_logits = discriminator(
                images=self.fake_images,
                labels=self.fake_labels,
                training=self.training,
                progress=self.progress,
                name="discriminator",
                reuse=True
            )
            #========================================================================#
            # hinge loss for discriminator and generator
            self.discriminator_loss = tf.reduce_mean(tf.nn.relu(1 - self.real_logits))
            self.discriminator_loss += tf.reduce_mean(tf.nn.relu(1 + self.fake_logits))
            self.generator_loss = -tf.reduce_mean(self.fake_logits)
            #========================================================================#
            # variables for discriminator and generator
            self.discriminator_variables = tf.get_collection(
                key=tf.GraphKeys.TRAINABLE_VARIABLES,
                scope="{}/discriminator".format(self.name)
            )
            self.generator_variables = tf.get_collection(
                key=tf.GraphKeys.TRAINABLE_VARIABLES,
                scope="{}/generator".format(self.name)
            )
            #========================================================================#
            # optimizer for discriminator and generator
            self.discriminator_optimizer = tf.train.AdamOptimizer(
                learning_rate=self.hyper_params.discriminator_learning_rate,
                beta1=self.hyper_params.discriminator_beta1,
                beta2=self.hyper_params.discriminator_beta2
            )
            self.generator_optimizer = tf.train.AdamOptimizer(
                learning_rate=self.hyper_params.generator_learning_rate,
                beta1=self.hyper_params.generator_beta1,
                beta2=self.hyper_params.generator_beta2
            )
            #========================================================================#
            # training op for generator and discriminator
            self.discriminator_train_op = self.discriminator_optimizer.minimize(
                loss=self.discriminator_loss,
                var_list=self.discriminator_variables
            )
            self.generator_train_op = self.generator_optimizer.minimize(
                loss=self.generator_loss,
                var_list=self.generator_variables,
                global_step=self.global_step
            )
            #========================================================================#
            # update ops for discriminator and generator
            # NOTE: tf.control_dependencies doesn't work
            self.discriminator_update_ops = tf.get_collection(
                key=tf.GraphKeys.UPDATE_OPS,
                scope="{}/discriminator".format(self.name)
            )
            self.generator_update_ops = tf.get_collection(
                key=tf.GraphKeys.UPDATE_OPS,
                scope="{}/generator".format(self.name)
            )
            self.discriminator_train_op = tf.group([self.discriminator_train_op, self.discriminator_update_ops])
            self.generator_train_op = tf.group([self.generator_train_op, self.generator_update_ops])
            #========================================================================#
            # utilities
            self.saver = tf.train.Saver()
            self.summary = tf.summary.merge([
                tf.summary.image("real_log_mel_magnitude_spectrograms", self.real_images[:, 0, ..., tf.newaxis], max_outputs=2),
                tf.summary.image("real_mel_instantaneous_frequencies", self.real_images[:, 1, ..., tf.newaxis], max_outputs=2),
                tf.summary.image("fake_log_mel_magnitude_spectrograms", self.fake_images[:, 0, ..., tf.newaxis], max_outputs=2),
                tf.summary.image("fake_mel_instantaneous_frequencies", self.fake_images[:, 1, ..., tf.newaxis], max_outputs=2),
                tf.summary.scalar("discriminator_loss", self.discriminator_loss),
                tf.summary.scalar("generator_loss", self.generator_loss)
            ])

    def initialize(self):

        session = tf.get_default_session()
        session.run(tf.tables_initializer())

        checkpoint = tf.train.latest_checkpoint(self.name)
        if checkpoint:
            self.saver.restore(session, checkpoint)
            tf.logging.info("{} restored".format(checkpoint))
        else:
            global_variables = tf.global_variables(scope=self.name)
            session.run(tf.variables_initializer(global_variables))
            tf.logging.info("global variables in {} initialized".format(self.name))

    def train(self, total_steps):

        session = tf.get_default_session()
        writer = tf.summary.FileWriter(self.name, session.graph)

        feed_dict = {
            self.training: True,
            self.total_steps: total_steps
        }

        while True:

            global_step = session.run(self.global_step)

            session.run(
                fetches=self.discriminator_train_op,
                feed_dict=feed_dict
            )
            session.run(
                fetches=self.generator_train_op,
                feed_dict=feed_dict
            )

            if global_step % 100 == 0:

                discriminator_loss, generator_loss = session.run(
                    fetches=[self.discriminator_loss, self.generator_loss],
                    feed_dict=feed_dict
                )
                tf.logging.info("global_step: {}, discriminator_loss: {:.2f}, generator_loss: {:.2f}".format(
                    global_step. discriminator_loss, generator_loss
                ))

                summary = session.run(
                    fetches=self.summary,
                    feed_dict=feed_dict
                )
                writer.add_summary(
                    summary=summary,
                    global_step=global_step
                )

                if global_step % 1000 == 0:

                    checkpoint = self.saver.save(
                        sess=session,
                        save_path=os.path.join(self.name, "model.ckpt"),
                        global_step=global_step
                    )

            if global_step == total_steps:
                break
