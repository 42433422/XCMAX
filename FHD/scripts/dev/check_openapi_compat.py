#!/usr/bin/env python3
"""Conservative backwards compatibility gate for the published OpenAPI contract."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

METHODS = frozenset('get put post delete options head patch trace'.split())


def resolve(doc, value):
    seen = set()
    while isinstance(value, dict) and '$ref' in value:
        ref = value['$ref']
        if not ref.startswith('#/') or ref in seen:
            raise ValueError(f'unsupported or cyclic reference: {ref}')
        seen.add(ref)
        target = doc
        for segment in ref[2:].split('/'):
            target = target[segment.replace('~1', '/').replace('~0', '~')]
        value = {**target, **{k: v for k, v in value.items() if k != '$ref'}}
    return value


def compare(old, new):
    problems = set()
    visited = set()

    def bad(where, reason):
        problems.add(f'{where}: {reason}')

    def schema(a, b, where, direction):
        key = (json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True), direction)
        if key in visited:
            return
        visited.add(key)
        a, b = resolve(old, a), resolve(new, b)
        if not isinstance(a, dict) or not isinstance(b, dict):
            if a != b:
                bad(where, 'boolean/schema contract changed')
            return
        for field in ('type', 'format', 'nullable', 'const', 'oneOf', 'anyOf', 'allOf', 'not',
                      'if', 'then', 'else', 'pattern', 'additionalProperties', 'discriminator',
                      'dependentRequired', 'prefixItems', 'contains'):
            if a.get(field) != b.get(field):
                bad(where, f'{field} changed (compatibility review required)')
        for field in ('minimum', 'exclusiveMinimum', 'minLength', 'minItems', 'minProperties',
                      'maximum', 'exclusiveMaximum', 'maxLength', 'maxItems', 'maxProperties',
                      'multipleOf', 'uniqueItems'):
            if a.get(field) != b.get(field):
                bad(where, f'{field} changed (compatibility review required)')
        if a.get('enum') != b.get('enum'):
            before, after = a.get('enum'), b.get('enum')
            if before is None:
                incompatible = direction == 'request'
            elif after is None:
                incompatible = direction == 'response'
            else:
                before = {json.dumps(v, sort_keys=True) for v in before}
                after = {json.dumps(v, sort_keys=True) for v in after}
                incompatible = not (before <= after if direction == 'request' else after <= before)
            if incompatible:
                bad(where, 'enum contract became incompatible')
        old_required = set(a.get('required', []))
        new_required = set(b.get('required', []))
        lost = new_required - old_required if direction == 'request' else old_required - new_required
        if lost:
            bad(where, f'{direction} required fields incompatible: {sorted(lost)}')
        ap, bp = a.get('properties', {}), b.get('properties', {})
        for name in sorted(ap.keys() - bp.keys()):
            bad(f'{where}.{name}', f'{direction} property removed')
        for name in sorted(ap.keys() & bp.keys()):
            schema(ap[name], bp[name], f'{where}.{name}', direction)
        if 'items' in a or 'items' in b:
            schema(a.get('items', {}), b.get('items', {}), f'{where}[]', direction)
        for field in ('oneOf', 'anyOf', 'allOf', 'prefixItems'):
            if a.get(field) == b.get(field):
                for i, (left, right) in enumerate(zip(a.get(field, []), b.get(field, []))):
                    schema(left, right, f'{where}.{field}[{i}]', direction)
        for field in ('additionalProperties', 'not', 'if', 'then', 'else', 'contains'):
            if isinstance(a.get(field), dict) and isinstance(b.get(field), dict):
                schema(a[field], b[field], f'{where}.{field}', direction)

    def content(a, b, where, direction):
        for media, av in a.items():
            if media not in b:
                bad(where, f'media type removed: {media}')
                continue
            schema(av.get('schema', {}), b[media].get('schema', {}), f'{where} {media}', direction)

    def parameters(doc, path, operation):
        values = {}
        for raw in path.get('parameters', []) + operation.get('parameters', []):
            p = resolve(doc, raw)
            values[(p['in'], p['name'])] = p
        return values

    for path, before_path in old['paths'].items():
        after_path = new['paths'].get(path, {})
        for method in METHODS & before_path.keys():
            where = f'{method.upper()} {path}'
            if method not in after_path:
                bad(where, 'operation removed')
                continue
            visited.clear()
            a, b = before_path[method], after_path[method]
            if a.get('operationId') != b.get('operationId'):
                bad(where, 'operationId changed')
            if a.get('security', old.get('security', [])) != b.get('security', new.get('security', [])):
                bad(where, 'security requirements changed (compatibility review required)')
            ap, bp = parameters(old, before_path, a), parameters(new, after_path, b)
            for name, param in bp.items():
                if param.get('required') and not ap.get(name, {}).get('required'):
                    bad(where, f'new required parameter: {name}')
            for name, param in ap.items():
                if name not in bp:
                    bad(where, f'parameter removed: {name}')
                    continue
                other = bp[name]
                for field in ('style', 'explode', 'allowReserved'):
                    if param.get(field) != other.get(field):
                        bad(where, f'parameter {name} {field} changed')
                schema(param.get('schema', {}), other.get('schema', {}), f'{where} parameter {name}', 'request')
                content(param.get('content', {}), other.get('content', {}), f'{where} parameter {name}', 'request')
            ab = resolve(old, a.get('requestBody', {}))
            bb = resolve(new, b.get('requestBody', {}))
            if bb.get('required') and not ab.get('required'):
                bad(where, 'request body became required')
            content(ab.get('content', {}), bb.get('content', {}), f'{where} request body', 'request')
            for code, raw in a.get('responses', {}).items():
                if code not in b.get('responses', {}):
                    bad(where, f'response status removed: {code}')
                    continue
                ar = resolve(old, raw)
                br = resolve(new, b['responses'][code])
                content(ar.get('content', {}), br.get('content', {}), f'{where} response {code}', 'response')
                ah, bh = ar.get('headers', {}), br.get('headers', {})
                for name, header in ah.items():
                    if name not in bh:
                        bad(where, f'response header removed: {code} {name}')
                    else:
                        schema(resolve(old, header).get('schema', {}), resolve(new, bh[name]).get('schema', {}),
                               f'{where} response {code} header {name}', 'response')
    return sorted(problems)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('baseline', type=Path)
    parser.add_argument('candidate', type=Path)
    args = parser.parse_args()
    old = json.loads(args.baseline.read_text(encoding='utf-8'))
    new = json.loads(args.candidate.read_text(encoding='utf-8'))
    if not all(isinstance(doc.get('paths'), dict) and doc['paths'] for doc in (old, new)):
        raise ValueError('missing or empty OpenAPI paths')
    problems = compare(old, new)
    for problem in problems:
        print(problem)
    print(f'OpenAPI compatibility: {len(problems)} change(s) requiring review')
    return int(bool(problems))


if __name__ == '__main__':
    raise SystemExit(main())
