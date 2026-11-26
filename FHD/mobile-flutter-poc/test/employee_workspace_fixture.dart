import 'dart:async';

import 'package:xcagi_flutter_poc/src/api/mobile_api.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_models.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_session_store.dart';
import 'package:xcagi_flutter_poc/src/data/ai_employee_profile.dart';
import 'package:xcagi_flutter_poc/src/data/mobile_repository.dart';

const employee = AiEmployeeProfile(
  modId: 'account-mod',
  modName: '企业应用',
  modDescription: '',
  modVersion: '',
  modAuthor: '',
  industryName: '',
  employeeId: 'employee-one',
  name: '订单助理',
  title: '订单助理',
  summary: '核对订单与进度',
  apiBasePath: '/api/mod/account-mod',
  phoneChannel: 'chat',
  workflowPlaceholder: false,
  profileSource: 'installed',
  marketConnected: true,
  marketPkgId: '',
  marketVersion: '',
  marketAuthor: '',
  marketMaterialCategory: '',
  marketLicenseScope: '',
  marketSecurityLevel: '',
);

class Api extends MobileApiClient {
  Api()
      : super(
            sessionStore: MemoryMobileSessionStore(MobileSessionData.empty
                .copyWith(
                    userId: 1,
                    accountKind: 'enterprise',
                    accessToken: 'account-one')));
  bool enabled = false;
  bool failPrefs = false;
  Completer<Map<String, Object?>>? pending;
  final writes = <(String, bool)>[];
  Map<String, Object?> response() => {
        'success': true,
        'owner_id': 'owner-one',
        'data': {
          'workflow_ai_employees': {'employee-one': enabled}
        }
      };
  @override
  Future<Map<String, Object?>> workspacePreferences() async {
    if (failPrefs) throw StateError('offline');
    return response();
  }

  @override
  Future<Map<String, Object?>> setWorkspaceEmployeeEnabled(
      String id, bool value,
      {required int expectedGeneration, required String expectedBase}) async {
    writes.add((id, value));
    if (pending != null) return pending!.future;
    enabled = value;
    return response();
  }
}

class Repository extends MobileRepository {
  Repository(Api api) : super(client: api);
  @override
  Future<List<AiEmployeeProfile>> loadAiEmployees() async => [employee];
  @override
  Future<List<MobileTaskSummary>> loadTasks({int limit = 50}) async => [];
}
