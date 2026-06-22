import { describe, it, expect } from '@ohos/hypium';
import {
  buildEmployees,
  buildConversations,
  findEmployee
} from '../../../../main/ets/state/AppDataBuilder';
import { AiEmployeeProfile, ModInfo, WorkflowEmployeeInfo } from '../../../../main/ets/models/MobileModels';

export default function appDataBuilderTest() {
  describe('AppDataBuilder', () => {
    // ── buildEmployees ──

    describe('buildEmployees', () => {
      it('emptyMods_returnsEmptyArray', 0, () => {
        const result = buildEmployees([]);
        expect(result.length).assertEqual(0);
      });

      it('modWithEmptyId_isSkipped', 0, () => {
        const mod: ModInfo = { id: '', name: 'Test' };
        const result = buildEmployees([mod]);
        expect(result.length).assertEqual(0);
      });

      it('modWithUndefinedId_isSkipped', 0, () => {
        const mod: ModInfo = { name: 'Test' };
        const result = buildEmployees([mod]);
        expect(result.length).assertEqual(0);
      });

      it('employeeWithEmptyId_isSkipped', 0, () => {
        const mod: ModInfo = {
          id: 'mod1',
          name: 'TestMod',
          workflow_employees: [{ id: '', label: 'Emp' }]
        };
        const result = buildEmployees([mod]);
        expect(result.length).assertEqual(0);
      });

      it('employeeWithEmptyLabel_isSkipped', 0, () => {
        const mod: ModInfo = {
          id: 'mod1',
          name: 'TestMod',
          workflow_employees: [{ id: 'emp1', label: '' }]
        };
        const result = buildEmployees([mod]);
        expect(result.length).assertEqual(0);
      });

      it('validModAndEmployee_returnsProfile', 0, () => {
        const mod: ModInfo = {
          id: 'mod1',
          name: 'TestMod',
          author: 'TestAuthor',
          description: 'A test mod',
          workflow_employees: [{
            id: 'emp1',
            label: 'Employee1',
            panel_title: 'Panel Title',
            panel_summary: 'Panel Summary',
            api_base_path: '/api/emp1',
            phone_channel: 'channel1',
            workflow_placeholder: false
          }]
        };
        const result = buildEmployees([mod]);
        expect(result.length).assertEqual(1);
        const emp = result[0];
        expect(emp.key).assertEqual('mod1:emp1');
        expect(emp.modId).assertEqual('mod1');
        expect(emp.modName).assertEqual('TestMod');
        expect(emp.modAuthor).assertEqual('TestAuthor');
        expect(emp.employeeId).assertEqual('emp1');
        expect(emp.name).assertEqual('Employee1');
        expect(emp.title).assertEqual('Panel Title');
        expect(emp.summary).assertEqual('Panel Summary');
        expect(emp.apiBasePath).assertEqual('/api/emp1');
        expect(emp.phoneChannel).assertEqual('channel1');
        expect(emp.placeholder).assertFalse();
        expect(emp.avatarText).assertEqual('E');
      });

      it('multipleMods_multipleEmployees_allReturned', 0, () => {
        const mods: ModInfo[] = [
          {
            id: 'mod1',
            name: 'Mod1',
            workflow_employees: [
              { id: 'emp1', label: 'Emp1' },
              { id: 'emp2', label: 'Emp2' }
            ]
          },
          {
            id: 'mod2',
            name: 'Mod2',
            workflow_employees: [
              { id: 'emp3', label: 'Emp3' }
            ]
          }
        ];
        const result = buildEmployees(mods);
        expect(result.length).assertEqual(3);
        expect(result[0].key).assertEqual('mod1:emp1');
        expect(result[1].key).assertEqual('mod1:emp2');
        expect(result[2].key).assertEqual('mod2:emp3');
      });

      it('placeholderEmployee_placeholderFlagTrue', 0, () => {
        const mod: ModInfo = {
          id: 'mod1',
          name: 'TestMod',
          workflow_employees: [{
            id: 'emp1',
            label: 'Emp1',
            workflow_placeholder: true
          }]
        };
        const result = buildEmployees([mod]);
        expect(result.length).assertEqual(1);
        expect(result[0].placeholder).assertTrue();
      });
    });

    // ── buildConversations ──

    describe('buildConversations', () => {
      it('emptyEmployees_returnsTwoFixedConversations', 0, () => {
        const result = buildConversations([]);
        expect(result.length).assertEqual(2);
        expect(result[0].id).assertEqual('assistant');
        expect(result[0].title).assertEqual('小C助理');
        expect(result[0].source).assertEqual('fixed');
        expect(result[1].id).assertEqual('customer-service');
        expect(result[1].title).assertEqual('专属客服');
        expect(result[1].source).assertEqual('fixed');
      });

      it('withEmployees_returnsFixedPlusDynamic', 0, () => {
        const employees: AiEmployeeProfile[] = [{
          key: 'mod1:emp1',
          modId: 'mod1',
          modName: 'TestMod',
          modAuthor: '',
          employeeId: 'emp1',
          name: 'TestEmp',
          title: 'Title',
          summary: 'Summary',
          apiBasePath: '',
          phoneChannel: '',
          placeholder: false,
          avatarText: 'T'
        }];
        const result = buildConversations(employees);
        expect(result.length).assertEqual(3);
        expect(result[2].id).assertEqual('employee:mod1:emp1');
        expect(result[2].title).assertEqual('TestEmp');
        expect(result[2].source).assertEqual('TestMod');
        expect(result[2].employeeKey).assertEqual('mod1:emp1');
      });
    });

    // ── findEmployee ──

    describe('findEmployee', () => {
      it('emptyArray_returnsUndefined', 0, () => {
        const result = findEmployee([], 'anyKey');
        expect(result).assertUndefined();
      });

      it('keyNotFound_returnsUndefined', 0, () => {
        const employees: AiEmployeeProfile[] = [{
          key: 'mod1:emp1',
          modId: 'mod1',
          modName: '',
          modAuthor: '',
          employeeId: 'emp1',
          name: 'Emp1',
          title: '',
          summary: '',
          apiBasePath: '',
          phoneChannel: '',
          placeholder: false,
          avatarText: 'E'
        }];
        const result = findEmployee(employees, 'nonexistent');
        expect(result).assertUndefined();
      });

      it('keyFound_returnsEmployee', 0, () => {
        const employees: AiEmployeeProfile[] = [{
          key: 'mod1:emp1',
          modId: 'mod1',
          modName: '',
          modAuthor: '',
          employeeId: 'emp1',
          name: 'Emp1',
          title: '',
          summary: '',
          apiBasePath: '',
          phoneChannel: '',
          placeholder: false,
          avatarText: 'E'
        }];
        const result = findEmployee(employees, 'mod1:emp1');
        expect(result).assertDeepEquals(employees[0]);
      });
    });
  });
}
