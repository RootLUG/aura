"""
This plugin captures data for research of cryptography usage
It looks up common RSA/DSA key generation functions and key sizes
"""

from . nodes import *
from .. import base
from .. import rules
from ...utils import Analyzer

# Key generation functions to lookup
CRYPTO_GEN_KEYS = {
    'cryptography.hazmat.primitives.asymmetric.dsa.generate_private_key': {
        'type': 'dsa', 'lib': 'cryptography'
    },
    'cryptography.hazmat.primitives.asymmetric.dsa.generate_parameters': {
        'type': 'dsa', 'lib': 'cryptography'
    },
    'cryptography.hazmat.primitives.asymmetric.rsa.generate_private_key': {
        'type': 'rsa', 'lib': 'cryptography'
    },
    'cryptography.hazmat.primitives.asymmetric.rsa.generate_parameters': {
        'type': 'rsa', 'lib': 'cryptography'
    },

    'Crypto.PublicKey.DSA.generate': {
        'type': 'dsa', 'lib': 'crypto'
    },
    'Crypto.PublicKey.RSA.generate': {
        'type': 'rsa', 'lib': 'crypto'
    },
    'Cryptodome.PublicKey.DSA.generate': {
        'type': 'dsa', 'lib': 'crypto'
    },
    'Cryptodome.PublicKey.RSA.generate': {
        'type': 'rsa', 'lib': 'crypto'
    }
}

# Minimum safe key sizes
MIN_KEY_SIZES = {
    'rsa': 2048,
    'dsa': 2048
}


class CryptoKeyGeneration(rules.Rule):
    """
    Detection hit to throw when crypto key generation is detected
    """
    pass


@Analyzer.ID('cryptography_generate_keys')
@Analyzer.description("Analyze the generation of cryptography keys")
class CryptoGenKey(base.NodeAnalyzerV2):
    """
    Lookup for function calls in the AST tree that are matching the key generation calls
    Attempt to parse the key type and key size into the detection hit
    """
    def node_Call(self, context):
        f_name = context.node.full_name

        if not isinstance(f_name, str):
            return

        if f_name in CRYPTO_GEN_KEYS:
            target = CRYPTO_GEN_KEYS.get(f_name)
            yield from getattr(self, f'_lib_{target["lib"]}')(context, target)
            return

    def _lib_cryptography(self, context, info):
        try:
            signature = context.node.apply_signature('key_size', backend=None)
        except TypeError:  # Signature call doesn't match parameters/kws
            return
        key_size = signature.args[0]
        if isinstance(key_size, Number):
            key_size = key_size.value
        elif not isinstance(key_size, int):
            return

        yield self._gen_hit(context, info, key_size)

    def _lib_crypto(self, context, info):
        try:
            signature = context.node.apply_signature('bits', randfunc=None, domain=None)
        except TypeError:
            return

        key_size = signature.args[0]
        if isinstance(key_size, Number):
            key_size = key_size.value
        elif not isinstance(key_size, int):
            return

        yield self._gen_hit(context, info, key_size)

    def _gen_hit(self, context, info, key_size=None):
        hit = CryptoKeyGeneration(
            message="Generation of cryptography key detected",
            signature=f"crypto#gen_key#{context.visitor.path}#{context.node.line_no}",
            extra={
                'function': context.node.full_name,
                'key_type': info['type'],
                'key_size': key_size
            }
        )

        if key_size is not None and key_size < MIN_KEY_SIZES.get(info['type'], 0):
            hit.score = 100

        return hit
