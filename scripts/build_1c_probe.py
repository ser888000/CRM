"""Build a private probe or receiver ERT using an owner-supplied, known shell.

Requires olefile (build tool only). No proprietary shell/module is in this repo.
All old executable module code is replaced; all other streams remain byte-identical.
The result still needs an actual 1C 7.7 smoke test.
"""
import argparse
import hashlib
import re
from pathlib import Path
import shutil
import zlib
import olefile

# Conv44.ert from the owner-supplied archive; prevents patching an unknown form.
DONOR_SHA256 = '905359f545348ce8ef6f77b3c4ae817533899f9296d95841a7732601fc899cca'


APPLICATION_DONOR_SHA256 = '00672d6eac1227d8193e0be608a84fb02a98218964a7b509e33b7ee9bcfde7b7'


UNIFIED_DONOR_SHA256 = '3fbc057970b208fb5ae9cca507f180a890e85bb7bd50e1c013306c7825a51a9e'


def unified_source(directory):
    """Compose only our modules, preserving literals and stage-specific helpers."""
    directory = Path(directory)
    wrapper = (directory / 'unified.1c').read_text()
    first_procedure = re.search(r'^(?:Процедура|Функция) ', wrapper, re.M)
    if first_procedure is None:
        raise ValueError('Unified entry module has no procedures.')
    header, entry = wrapper[:first_procedure.start()], wrapper[first_procedure.start():]
    shared = {'crmUUID', 'crmError', 'crmExisting'}
    seen = {}
    blocks = []
    definitions = re.compile(r'^(?:Функция|Процедура) (\w+).*?^Конец(?:Функции|Процедуры)', re.M | re.S)
    tokens = re.compile(r'"(?:""|[^"\n])*"|//[^\n]*|\b[A-Za-z_]\w*\b')
    for module, prefix in [('application', 'a_'), ('voucher', 'v_'),
                           ('shipment', 's_'), ('payment', 'p_')]:
        source = (directory / (module + '.1c')).read_text()
        functions = [(match[1], match[0]) for match in definitions.finditer(source)
                     if match[1] != 'ПриОткрытии']
        names = {name: prefix + name for name, _ in functions if name not in shared}
        for name, body in functions:
            if name in shared:
                normalized = re.sub(r'\s+', '', re.sub(r'//[^\n]*', '', body))
                if name in seen:
                    if seen[name] != normalized:
                        raise ValueError('Shared helper differs between stages: ' + name)
                    continue
                seen[name] = normalized
            # Rename identifier tokens, never text in a message, XML attribute or comment.
            body = tokens.sub(lambda match: names.get(match[0], match[0]), body)
            blocks.append(body)
    if set(seen) != shared:
        raise ValueError('Missing unified shared helpers.')
    common = (directory / 'application_services.1c').read_text()
    return header + common + '\n' + '\n\n'.join(blocks) + '\n\n' + entry


def build(donor, output, application=False, voucher=False, shipment=False, payment=False, unified=False):
    donor, output = Path(donor), Path(output)
    if donor.resolve() == output.resolve():
        raise ValueError('Output must differ from the original.')
    if sum((application, voucher, shipment, payment, unified)) > 1:
        raise ValueError('Select one module mode.')
    expected = (UNIFIED_DONOR_SHA256 if unified else APPLICATION_DONOR_SHA256
                if application or voucher or shipment or payment else DONOR_SHA256)
    if hashlib.sha256(donor.read_bytes()).hexdigest() != expected:
        raise ValueError('Use the inspected shell for the selected mode.')
    module = ('payment.1c' if payment else 'shipment.1c' if shipment else 'voucher.1c' if voucher else
              'application.1c' if application else 'probe.1c')
    source = Path(__file__).resolve().parents[1] / 'integrations/1c77' / module
    source_text = unified_source(source.parent) if unified else source.read_text()
    if application or voucher or shipment:
        common = (source.parent / 'application_services.1c').read_text()
        source_text = source_text.replace('\nФункция ', '\n' + common + '\nФункция ', 1)
    text = source_text.replace('\r\n', '\n').replace('\n', '\r\n').encode('cp1251')
    compressor = zlib.compressobj(9, zlib.DEFLATED, -15)
    module = compressor.compress(text) + compressor.flush()
    with olefile.OleFileIO(donor) as original:
        streams = {tuple(path): original.openstream(path).read() for path in original.listdir()}
    size = len(streams[('MD Programm text',)])
    if len(module) > size:
        raise ValueError('Module exceeds shell stream capacity.')
    shutil.copyfile(donor, output)
    output.chmod(0o600)
    with olefile.OleFileIO(output, write_mode=True) as ole:
        ole.write_stream('MD Programm text', module.ljust(size, b'\0'))
    with olefile.OleFileIO(output) as ole:
        assert zlib.decompress(ole.openstream('MD Programm text').read(), -15) == text
        for path, original in streams.items():
            if path != ('MD Programm text',):
                assert ole.openstream(list(path)).read() == original
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('donor')
    parser.add_argument('output')
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--application', action='store_true')
    modes.add_argument('--voucher', action='store_true')
    modes.add_argument('--shipment', action='store_true')
    modes.add_argument('--payment', action='store_true')
    modes.add_argument('--unified', action='store_true')
    args = parser.parse_args()
    print(build(args.donor, args.output, application=args.application, voucher=args.voucher, shipment=args.shipment, payment=args.payment, unified=args.unified))
