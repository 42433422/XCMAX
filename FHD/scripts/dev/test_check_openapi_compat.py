import copy
import unittest

from check_openapi_compat import compare


class CompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.old = {'paths': {'/tasks': {'post': {
            'operationId': 'submit',
            'parameters': [{'name': 'tenant', 'in': 'header', 'schema': {'type': 'string'}}],
            'requestBody': {'content': {'application/json': {'schema': {'$ref': '#/components/schemas/Input'}}}},
            'responses': {'200': {'content': {'application/json': {'schema': {'$ref': '#/components/schemas/Result'}}}}},
        }}}, 'components': {'schemas': {
            'Input': {'type': 'object', 'properties': {'task': {'type': 'string'}, 'mode': {'enum': ['a', 'b']}}},
            'Result': {'type': 'object', 'properties': {'id': {'type': 'string'}, 'state': {'enum': ['ok', 'failed']}}, 'required': ['id']},
        }}}
        self.new = copy.deepcopy(self.old)
        self.schemas = self.new['components']['schemas']
        self.op = self.new['paths']['/tasks']['post']

    def test_unchanged_and_additive(self):
        self.assertEqual(compare(self.old, self.new), [])
        self.schemas['Input']['properties']['optional'] = {'type': 'string'}
        self.schemas['Input']['properties']['mode']['enum'].append('c')
        self.schemas['Result']['properties']['state']['enum'].remove('failed')
        self.schemas['Result']['properties']['new'] = {'type': 'string'}
        self.assertEqual(compare(self.old, self.new), [])

    def test_removed_operation(self):
        del self.new['paths']['/tasks']
        self.assertIn('operation removed', '\n'.join(compare(self.old, self.new)))

    def test_required_parameter_and_body(self):
        self.op['parameters'][0]['required'] = True
        self.op['requestBody']['required'] = True
        issues = '\n'.join(compare(self.old, self.new))
        self.assertIn('new required parameter', issues)
        self.assertIn('request body became required', issues)

    def test_nested_reference_changes(self):
        self.schemas['Input']['required'] = ['task']
        self.schemas['Result']['properties']['id']['type'] = 'integer'
        self.schemas['Result']['required'] = []
        issues = '\n'.join(compare(self.old, self.new))
        self.assertIn('request required fields incompatible', issues)
        self.assertIn('response required fields incompatible', issues)
        self.assertIn('.id: type changed', issues)

    def test_enums(self):
        self.schemas['Input']['properties']['mode']['enum'].remove('b')
        self.schemas['Result']['properties']['state']['enum'].append('unknown')
        self.assertEqual(sum('enum contract' in x for x in compare(self.old, self.new)), 2)

    def test_removed_media_and_status(self):
        self.op['responses']['200']['content'] = {}
        self.op['responses']['201'] = {}
        self.assertIn('media type removed', '\n'.join(compare(self.old, self.new)))
        del self.op['responses']['200']
        self.assertIn('response status removed', '\n'.join(compare(self.old, self.new)))

    def test_recursive_reference_and_composed_schema(self):
        for doc in (self.old, self.new):
            model = doc['components']['schemas']['Result']
            model['properties']['child'] = {'anyOf': [{'$ref': '#/components/schemas/Result'}, {'type': 'null'}]}
        self.assertEqual(compare(self.old, self.new), [])
        self.schemas['Result']['properties']['id']['type'] = 'integer'
        self.assertTrue(compare(self.old, self.new))


if __name__ == '__main__':
    unittest.main()
