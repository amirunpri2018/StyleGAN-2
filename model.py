import tensorflow as tf


class GAN(object):

    def __init__(self, generator, discriminator, real_input_fn, fake_input_fn, hyper_params):

        # =========================================================================================
        real_images = real_input_fn()
        high_level_latents, low_level_latents = fake_input_fn()
        # =========================================================================================
        fake_images = generator(high_level_latents, low_level_latents)
        # =========================================================================================
        real_logits = discriminator(real_images)
        fake_logits = discriminator(fake_images)
        # =========================================================================================
        # Non-Saturating + Zero-Centered Gradient Penalty
        # [Generative Adversarial Networks]
        # (https://arxiv.org/abs/1406.2661)
        # [Which Training Methods for GANs do actually Converge?]
        # (https://arxiv.org/pdf/1801.04406.pdf)
        # -----------------------------------------------------------------------------------------
        # generator
        # non-saturating loss
        generator_losses = tf.nn.softplus(-fake_logits)
        # -----------------------------------------------------------------------------------------
        # discriminator
        # non-saturating loss
        discriminator_losses = tf.nn.softplus(-real_logits)
        discriminator_losses += tf.nn.softplus(fake_logits)
        # zero-centerd gradient penalty on data distribution
        if hyper_params.real_zero_centered_gradient_penalty_weight:
            real_gradients = tf.gradients(real_logits, [real_images])[0]
            real_gradient_penalties = tf.reduce_sum(tf.square(real_gradients), axis=[1, 2, 3])
            discriminator_losses += 0.5 * hyper_params.real_zero_centered_gradient_penalty_weight * real_gradient_penalties
        # zero-centerd gradient penalty on generator distribution
        if hyper_params.fake_zero_centered_gradient_penalty_weight:
            fake_gradients = tf.gradients(fake_logits, [fake_images])[0]
            fake_gradient_penalties = tf.reduce_sum(tf.square(fake_gradients), axis=[1, 2, 3])
            discriminator_losses += 0.5 * hyper_params.fake_zero_centered_gradient_penalty_weight * fake_gradient_penalties
        # =========================================================================================
        # losss reduction
        self.generator_loss = tf.reduce_mean(generator_losses)
        self.discriminator_loss = tf.reduce_mean(discriminator_losses)
        # =========================================================================================
        generator_optimizer = tf.train.AdamOptimizer(
            learning_rate=hyper_params.generator_learning_rate,
            beta1=hyper_params.generator_beta1,
            beta2=hyper_params.generator_beta2
        )
        discriminator_optimizer = tf.train.AdamOptimizer(
            learning_rate=hyper_params.discriminator_learning_rate,
            beta1=hyper_params.discriminator_beta1,
            beta2=hyper_params.discriminator_beta2
        )
        # -----------------------------------------------------------------------------------------
        generator_variables = tf.get_collection(tf.GraphKeys.TRAINABLE_VARIABLES, scope="generator")
        discriminator_variables = tf.get_collection(tf.GraphKeys.TRAINABLE_VARIABLES, scope="discriminator")
        # =========================================================================================
        self.generator_train_op = generator_optimizer.minimize(
            loss=self.generator_loss,
            var_list=generator_variables,
            global_step=tf.train.get_or_create_global_step()
        )
        self.discriminator_train_op = discriminator_optimizer.minimize(
            loss=self.discriminator_loss,
            var_list=discriminator_variables
        )
        # =========================================================================================
        # scaffold
        self.scaffold = tf.train.Scaffold(
            init_op=tf.global_variables_initializer(),
            local_init_op=tf.tables_initializer(),
            saver=tf.train.Saver(
                max_to_keep=10,
                keep_checkpoint_every_n_hours=12,
            ),
            summary_op=tf.summary.merge([
                tf.summary.image(
                    name="real_images",
                    tensor=tf.transpose(real_images, [0, 2, 3, 1]),
                    max_outputs=4
                ),
                tf.summary.image(
                    name="fake_images",
                    tensor=tf.transpose(fake_images, [0, 2, 3, 1]),
                    max_outputs=4
                ),
                tf.summary.scalar(
                    name="generator_loss",
                    tensor=self.generator_loss
                ),
                tf.summary.scalar(
                    name="discriminator_loss",
                    tensor=self.discriminator_loss
                ),
            ])
        )

    def train(self, total_steps, model_dir, save_checkpoint_steps,
              save_summary_steps, log_step_count_steps, config):

        with tf.train.SingularMonitoredSession(
            scaffold=self.scaffold,
            checkpoint_dir=model_dir,
            config=config,
            hooks=[
                tf.train.CheckpointSaverHook(
                    checkpoint_dir=model_dir,
                    save_steps=save_checkpoint_steps,
                    scaffold=self.scaffold,
                ),
                tf.train.SummarySaverHook(
                    output_dir=model_dir,
                    save_steps=save_summary_steps,
                    scaffold=self.scaffold
                ),
                tf.train.LoggingTensorHook(
                    tensors=dict(
                        global_step=tf.train.get_global_step(),
                        generator_loss=self.generator_loss,
                        discriminator_loss=self.discriminator_loss
                    ),
                    every_n_iter=log_step_count_steps,
                ),
                tf.train.StepCounterHook(
                    output_dir=model_dir,
                    every_n_steps=log_step_count_steps,
                ),
                tf.train.StopAtStepHook(
                    last_step=total_steps
                )
            ]
        ) as session:

            while not session.should_stop():
                session.run(self.discriminator_train_op)
                session.run(self.generator_train_op)
