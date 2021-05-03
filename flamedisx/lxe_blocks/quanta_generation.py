import numpy as np
from scipy import stats
import tensorflow as tf
import tensorflow_probability as tfp

import flamedisx as fd
export, __all__ = fd.exporter()
o = tf.newaxis


DEFAULT_WORK_PER_QUANTUM = 13.7e-3


@export
class MakeERQuanta(fd.Block):

    dimensions = ('quanta_produced', 'energy')
    extra_dimensions = (('quanta_produced_noStep', False),)
    depends_on = ((('energy',), 'rate_vs_energy'),)
    model_functions = ('work',)

    work = DEFAULT_WORK_PER_QUANTUM

    def _compute(self,
                 data_tensor, ptensor,
                 # Domain
                 quanta_produced,
                 # Dependency domain and value
                 energy, rate_vs_energy,
                 # Extra tensors for internal use
                 quanta_produced_noStep, energy_noStep):

        # Assume the intial number of quanta is always the same for each energy
        work = self.gimme('work', data_tensor=data_tensor, ptensor=ptensor)
        quanta_produced_real = tf.cast(
            tf.floor(energy_noStep / work[:, o, o]),
            dtype=fd.float_type())

        # (n_events, |nq|, |ne|) tensor giving p(nq | e)
        result = tf.cast(tf.equal(quanta_produced_noStep,
        quanta_produced_real), dtype=fd.float_type())

        padding = int(tf.floor(tf.shape(quanta_produced_noStep)[1] / \
        (tf.shape(quanta_produced)[1]-1))) - \
        tf.shape(quanta_produced_noStep)[1] % (tf.shape(quanta_produced)[1]-1)

        result_pad_left = tf.pad(result, [[0, 0], [padding, 0], [0, 0]])
        result_pad_right = tf.pad(result, [[0, 0], [0, padding], [0, 0]])

        chunks = int(tf.shape(result_pad_left)[1] / tf.shape(quanta_produced)[1])
        steps = self.source._fetch('quanta_produced_steps',
        data_tensor=data_tensor)

        result_temp_left = tf.reshape(result_pad_left,
        [tf.shape(result_pad_left)[0],
        int(tf.shape(result_pad_left)[1] / chunks), chunks,
        tf.shape(result_pad_left)[2]])
        result_left = tf.reduce_sum(result_temp_left, axis=2) \
        / (steps[:, o ,o] * steps[:, o ,o])

        result_temp_right = tf.reshape(result_pad_right,
        [tf.shape(result_pad_right)[0],
        int(tf.shape(result_pad_right)[1] / chunks), chunks,
        tf.shape(result_pad_right)[2]])
        result_right = tf.reduce_sum(result_temp_right, axis=2) \
        / (steps[:, o ,o] * steps[:, o ,o])

        return (result_left + result_right) / 2

    def _simulate(self, d):
        work = self.gimme_numpy('work')
        d['quanta_produced'] = np.floor(d['energy'].values
                                        / work).astype(np.int)

    def _annotate(self, d):
        d['quanta_produced_noStep_min'] = (
                d['electrons_produced_min']
                + d['photons_produced_min'])
        annotate_ces(self, d)

    def _domain_dict_bonus(self, d):
        return domain_dict_bonus(self, d)

    def _calculate_dimsizes_special(self):
        return calculate_dimsizes_special(self)


@export
class MakeNRQuanta(fd.Block):

    dimensions = ('quanta_produced', 'energy')
    extra_dimensions = (('quanta_produced_noStep', False),)
    depends_on = ((('energy',), 'rate_vs_energy'),)

    special_model_functions = ('lindhard_l',)
    model_functions = ('work',) + special_model_functions

    work = DEFAULT_WORK_PER_QUANTUM

    @staticmethod
    def lindhard_l(e, lindhard_k=tf.constant(0.138, dtype=fd.float_type())):
        """Return Lindhard quenching factor at energy e in keV"""
        eps = e * tf.constant(11.5 * 54.**(-7./3.), dtype=fd.float_type())  # Xenon: Z = 54

        n0 = tf.constant(3., dtype=fd.float_type())
        n1 = tf.constant(0.7, dtype=fd.float_type())
        n2 = tf.constant(1.0, dtype=fd.float_type())
        p0 = tf.constant(0.15, dtype=fd.float_type())
        p1 = tf.constant(0.6, dtype=fd.float_type())

        g = n0 * tf.pow(eps, p0) + n1 * tf.pow(eps, p1) + eps
        res = lindhard_k * g/(n2 + lindhard_k * g)
        return res

    def _compute(self,
                 data_tensor, ptensor,
                 # Domain
                 quanta_produced,
                 # Dependency domain and value
                 energy, rate_vs_energy,
                 # Extra tensors for internal use
                 quanta_produced_noStep, energy_noStep):

        work = self.gimme('work', data_tensor=data_tensor, ptensor=ptensor)
        mean_q_produced = (
                energy_noStep
                * self.gimme('lindhard_l', bonus_arg=energy_noStep,
                             data_tensor=data_tensor, ptensor=ptensor)
                / work[:, o, o])

        # (n_events, |nq|, |ne|) tensor giving p(nq | e)
        result = tfp.distributions.Poisson(mean_q_produced).prob(
        quanta_produced_noStep)

        padding = int(tf.floor(tf.shape(quanta_produced_noStep)[1] / \
        (tf.shape(quanta_produced)[1]-1))) - \
        tf.shape(quanta_produced_noStep)[1] % (tf.shape(quanta_produced)[1]-1)

        result_pad_left = tf.pad(result, [[0, 0], [padding, 0], [0, 0]])
        result_pad_right = tf.pad(result, [[0, 0], [0, padding], [0, 0]])

        chunks = int(tf.shape(result_pad_left)[1] / tf.shape(quanta_produced)[1])
        steps = self.source._fetch('quanta_produced_steps',
        data_tensor=data_tensor)

        result_temp_left = tf.reshape(result_pad_left,
        [tf.shape(result_pad_left)[0],
        int(tf.shape(result_pad_left)[1] / chunks), chunks,
        tf.shape(result_pad_left)[2]])
        result_left = tf.reduce_sum(result_temp_left, axis=2) \
        / (steps[:, o ,o] * steps[:, o ,o])

        result_temp_right = tf.reshape(result_pad_right,
        [tf.shape(result_pad_right)[0],
        int(tf.shape(result_pad_right)[1] / chunks), chunks,
        tf.shape(result_pad_right)[2]])
        result_right = tf.reduce_sum(result_temp_right, axis=2) \
        / (steps[:, o ,o] * steps[:, o ,o])

        return (result_left + result_right) / 2

    def _simulate(self, d):
        # If you forget the .values here, you may get a Python core dump...
        energies = d['energy'].values
        work = self.gimme_numpy('work')
        lindhard_l = self.gimme_numpy('lindhard_l', bonus_arg=energies)
        d['quanta_produced'] = stats.poisson.rvs(energies * lindhard_l / work)

    def _annotate(self, d):
        d['quanta_produced_noStep_min'] = (
                d['electrons_produced_min']
                + d['photons_produced_min'])
        annotate_ces(self, d)

    def _domain_dict_bonus(self, d):
        return domain_dict_bonus(self, d)

    def _calculate_dimsizes_special(self):
        return calculate_dimsizes_special(self)


def annotate_ces(self, d):
    # No bounds need to be estimated; we will consider the entire
    # energy spectrum for each event.

    # Nonetheless, it's useful to reconstruct the 'visible' energy
    # via the combined energy scale (CES
    work = self.gimme_numpy('work')
    d['e_charge_vis'] = work * d['electrons_produced_mle']
    d['e_light_vis'] = work * d['photons_produced_mle']
    d['e_vis'] = d['e_charge_vis'] + d['e_light_vis']

    for bound in ('min', 'max'):
        d['quanta_produced_' + bound] = (
                d['electrons_produced_' + bound]
                + d['photons_produced_' + bound])

def domain_dict_bonus(self, d):
    # Calculate cross_domains
    mi = self.source._fetch('quanta_produced_noStep_min',data_tensor=d)[:, o]
    quanta_produced_noStep_domain = mi + tf.range(tf.reduce_max(
    self.source._fetch('quanta_produced_noStep_dimsizes', data_tensor=d)))
    energy_domain = self.source.domain('energy', d)

    quanta_produced_noStep = tf.repeat(quanta_produced_noStep_domain[:, :, o],
    tf.shape(energy_domain)[1], axis=2)
    energy_noStep = tf.repeat(energy_domain[:, o, :],
    tf.shape(quanta_produced_noStep_domain)[1], axis=1)

    # Return as domain_dict
    return dict({'quanta_produced_noStep': quanta_produced_noStep,
    'energy_noStep': energy_noStep})

def calculate_dimsizes_special(self):
    d = self.source.data

    quanta_steps = (d['electrons_produced_steps'] <
    d['photons_produced_steps']) * d['electrons_produced_steps']
    + (d['photons_produced_steps'] <
    d['electrons_produced_steps']) * d['photons_produced_steps']

    batch_size = self.source.batch_size
    n_batches = self.source.n_batches

    for i in range(n_batches):
        quanta_steps[i * batch_size : (i + 1) * batch_size + 1] = \
        max(quanta_steps[i * batch_size : (i + 1) * batch_size + 1])

    d['electrons_produced_steps'] = quanta_steps
    d['photons_produced_steps'] = quanta_steps
    d['quanta_produced_steps'] = quanta_steps
    d['quanta_produced_noStep_steps'] = 1

    electrons_produced_dimsizes = np.ceil((
    d['electrons_produced_max'].to_numpy() \
    - d['electrons_produced_min'].to_numpy()) / quanta_steps) + 1
    self.source.dimsizes['electrons_produced'] = electrons_produced_dimsizes

    photons_produced_dimsizes = np.ceil((
    d['photons_produced_max'].to_numpy() \
    - d['photons_produced_min'].to_numpy()) / quanta_steps) + 1
    self.source.dimsizes['photons_produced'] =  photons_produced_dimsizes

    quanta_produced_dimsizes = electrons_produced_dimsizes \
    + photons_produced_dimsizes - 1

    for i in range(n_batches):
        quanta_produced_dimsizes[i * batch_size : (i + 1) * batch_size + 1] = \
        max(quanta_produced_dimsizes[i * batch_size :
        (i + 1) * batch_size + 1])

    self.source.dimsizes['quanta_produced'] = quanta_produced_dimsizes

    self.source.dimsizes['quanta_produced_noStep'] = quanta_produced_dimsizes \
    + (quanta_steps - 1) * (quanta_produced_dimsizes - 1)
