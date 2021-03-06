# Copyright 2016 The TensorFlow Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================
"""Tests for Monte Carlo Ops."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import tensorflow as tf

distributions = tf.contrib.distributions
layers = tf.contrib.layers
monte_carlo = tf.contrib.bayesflow.monte_carlo


class ExpectationImportanceSampleTest(tf.test.TestCase):

  def test_normal_integral_mean_and_var_correctly_estimated(self):
    n = int(1e6)
    with self.test_session():
      mu_p = tf.constant([-1.0, 1.0], dtype=tf.float64)
      mu_q = tf.constant([0.0, 0.0], dtype=tf.float64)
      sigma_p = tf.constant([0.5, 0.5], dtype=tf.float64)
      sigma_q = tf.constant([1.0, 1.0], dtype=tf.float64)
      p = distributions.Normal(mu=mu_p, sigma=sigma_p)
      q = distributions.Normal(mu=mu_q, sigma=sigma_q)

      # Compute E_p[X].
      e_x = monte_carlo.expectation_importance_sampler(
          f=lambda x: x, log_p=p.log_prob, sampling_dist_q=q, n=n, seed=42)

      # Compute E_p[X^2].
      e_x2 = monte_carlo.expectation_importance_sampler(
          f=tf.square,
          log_p=p.log_prob,
          sampling_dist_q=q,
          n=n,
          seed=42)

      stdev = tf.sqrt(e_x2 - tf.square(e_x))

      # Relative tolerance (rtol) chosen 2 times as large as minimim needed to
      # pass.
      # Convergence of mean is +- 0.003 if n = 100M
      # Convergence of std is +- 0.00001 if n = 100M
      self.assertEqual(p.get_batch_shape(), e_x.get_shape())
      self.assertAllClose(p.mean().eval(), e_x.eval(), rtol=0.01)
      self.assertAllClose(p.std().eval(), stdev.eval(), rtol=0.02)

  def test_multivariate_normal_prob_positive_product_of_components(self):
    # Test that importance sampling can correctly estimate the probability that
    # the product of components in a MultivariateNormal are > 0.
    n = 1000
    with self.test_session():
      p = distributions.MultivariateNormalDiag(
          mu=[0.0, 0.0], diag_stdev=[1.0, 1.0])
      q = distributions.MultivariateNormalDiag(
          mu=[0.5, 0.5], diag_stdev=[3., 3.])

      # Compute E_p[X_1 * X_2 > 0], with X_i the ith component of X ~ p(x).
      # Should equal 1/2 because p is a spherical Gaussian centered at (0, 0).
      def indicator(x):
        x1_times_x2 = tf.reduce_prod(x, reduction_indices=[-1])
        return 0.5 * (tf.sign(x1_times_x2) + 1.0)

      prob = monte_carlo.expectation_importance_sampler(
          f=indicator, log_p=p.log_prob, sampling_dist_q=q, n=n, seed=42)

      # Relative tolerance (rtol) chosen 2 times as large as minimim needed to
      # pass.
      # Convergence is +- 0.004 if n = 100k.
      self.assertEqual(p.get_batch_shape(), prob.get_shape())
      self.assertAllClose(0.5, prob.eval(), rtol=0.05)


class ExpectationImportanceSampleLogspaceTest(tf.test.TestCase):

  def test_normal_distribution_second_moment_estimated_correctly(self):
    # Test the importance sampled estimate against an analytical result.
    n = int(1e6)
    with self.test_session():
      mu_p = tf.constant([0.0, 0.0], dtype=tf.float64)
      mu_q = tf.constant([-1.0, 1.0], dtype=tf.float64)
      sigma_p = tf.constant([1.0, 2 / 3.], dtype=tf.float64)
      sigma_q = tf.constant([1.0, 1.0], dtype=tf.float64)
      p = distributions.Normal(mu=mu_p, sigma=sigma_p)
      q = distributions.Normal(mu=mu_q, sigma=sigma_q)

      # Compute E_p[X^2].
      # Should equal [1, (2/3)^2]
      log_e_x2 = monte_carlo.expectation_importance_sampler_logspace(
          log_f=lambda x: tf.log(tf.square(x)),
          log_p=p.log_prob,
          sampling_dist_q=q,
          n=n,
          seed=42)
      e_x2 = tf.exp(log_e_x2)

      # Relative tolerance (rtol) chosen 2 times as large as minimim needed to
      # pass.
      self.assertEqual(p.get_batch_shape(), e_x2.get_shape())
      self.assertAllClose([1., (2 / 3.)**2], e_x2.eval(), rtol=0.02)


class ExpectationTest(tf.test.TestCase):

  def test_mc_estimate_of_normal_mean_and_variance_is_correct_vs_analytic(self):
    n = 10000
    with self.test_session():
      p = distributions.Normal(mu=[1.0, -1.0], sigma=[0.3, 0.5])
      # Compute E_p[X] and E_p[X^2].
      z = p.sample_n(n=n)
      e_x = monte_carlo.expectation(lambda x: x, p, z=z, seed=42)
      e_x2 = monte_carlo.expectation(tf.square, p, z=z, seed=0)
      var = e_x2 - tf.square(e_x)

      self.assertEqual(p.get_batch_shape(), e_x.get_shape())
      self.assertEqual(p.get_batch_shape(), e_x2.get_shape())

      # Relative tolerance (rtol) chosen 2 times as large as minimim needed to
      # pass.
      self.assertAllClose(p.mean().eval(), e_x.eval(), rtol=0.01)
      self.assertAllClose(p.variance().eval(), var.eval(), rtol=0.02)


class GetSamplesTest(tf.test.TestCase):
  """Test the private method 'get_samples'."""

  def test_raises_if_both_z_and_n_are_none(self):
    with self.test_session():
      dist = distributions.Normal(mu=0., sigma=1.)
      z = None
      n = None
      seed = None
      with self.assertRaisesRegexp(ValueError, 'exactly one'):
        monte_carlo._get_samples(dist, z, n, seed)

  def test_raises_if_both_z_and_n_are_not_none(self):
    with self.test_session():
      dist = distributions.Normal(mu=0., sigma=1.)
      z = dist.sample_n(n=1)
      n = 1
      seed = None
      with self.assertRaisesRegexp(ValueError, 'exactly one'):
        monte_carlo._get_samples(dist, z, n, seed)

  def test_returns_n_samples_if_n_provided(self):
    with self.test_session():
      dist = distributions.Normal(mu=0., sigma=1.)
      z = None
      n = 10
      seed = None
      z = monte_carlo._get_samples(dist, z, n, seed)
      self.assertEqual((10,), z.get_shape())

  def test_returns_z_if_z_provided(self):
    with self.test_session():
      dist = distributions.Normal(mu=0., sigma=1.)
      z = dist.sample_n(n=10)
      n = None
      seed = None
      z = monte_carlo._get_samples(dist, z, n, seed)
      self.assertEqual((10,), z.get_shape())


if __name__ == '__main__':
  tf.test.main()
