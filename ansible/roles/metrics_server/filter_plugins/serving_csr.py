"""Validate an inventory-bound kubelet serving CSR before approval."""
import base64
import copy
import ipaddress
import re
from ansible.errors import AnsibleFilterError
from cryptography import x509
from cryptography.hazmat.primitives.asymmetric import rsa, ec
from cryptography.x509.oid import NameOID, ExtensionOID


def serving_approval(resource, node_name, node_ip):
    try:
        item = copy.deepcopy(resource)
        spec = item['spec']
        meta = item['metadata']
        identity = 'system:node:' + node_name
        if not re.fullmatch(r'csr-[a-z0-9]+', meta['name']) or not meta.get('uid') or not meta.get('resourceVersion'):
            raise ValueError('Require a named, versioned CSR resource')
        if spec['signerName'] != 'kubernetes.io/kubelet-serving' or spec['username'] != identity:
            raise ValueError('CSR signer or authenticated node identity differs')
        if set(spec.get('groups', [])) != {'system:nodes', 'system:authenticated'}:
            raise ValueError('Unexpected CSR authentication groups')
        if set(spec['usages']) not in ({'digital signature', 'key encipherment', 'server auth'},
                                       {'digital signature', 'server auth'}):
            raise ValueError('Serving CSR usages differ from the reviewed profile')
        if item.get('status', {}).get('conditions') or item.get('status', {}).get('certificate'):
            raise ValueError('Only a pending unapproved CSR may be approved')
        csr = x509.load_pem_x509_csr(base64.b64decode(spec['request'], validate=True))
        if not csr.is_signature_valid:
            raise ValueError('Invalid CSR signature')
        expected_subject = x509.Name([x509.NameAttribute(NameOID.ORGANIZATION_NAME, 'system:nodes'),
                                      x509.NameAttribute(NameOID.COMMON_NAME, identity)])
        if sorted((x.oid.dotted_string, x.value) for x in csr.subject) != sorted((x.oid.dotted_string, x.value) for x in expected_subject):
            raise ValueError('CSR subject differs from the authenticated node')
        key = csr.public_key()
        if not ((isinstance(key, rsa.RSAPublicKey) and key.key_size >= 2048) or
                (isinstance(key, ec.EllipticCurvePublicKey) and key.key_size >= 256)):
            raise ValueError('Unsupported or weak CSR key')
        if {extension.oid for extension in csr.extensions} != {ExtensionOID.SUBJECT_ALTERNATIVE_NAME}:
            raise ValueError('Unexpected certificate extensions')
        san = csr.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        if any(not isinstance(value, (x509.DNSName, x509.IPAddress)) for value in san):
            raise ValueError('Unexpected SAN type')
        if san.get_values_for_type(x509.DNSName) != [node_name]:
            raise ValueError('DNS SAN must match exactly this inventory node')
        if san.get_values_for_type(x509.IPAddress) != [ipaddress.IPv4Address(node_ip)]:
            raise ValueError('IP SAN must match exactly this node management address')
        item.pop('managedFields', None)
        meta.pop('managedFields', None)
        item['status'] = {'conditions': [{'type': 'Approved', 'status': 'True',
                                         'reason': 'InventoryServingIdentityVerified',
                                         'message': 'Authenticated node, subject, usages, signature and management SANs verified.'}]}
        return item
    except (KeyError, TypeError, ValueError) as error:
        raise AnsibleFilterError(str(error)) from error


class FilterModule:
    def filters(self):
        return {'metrics_server_serving_approval': serving_approval}
