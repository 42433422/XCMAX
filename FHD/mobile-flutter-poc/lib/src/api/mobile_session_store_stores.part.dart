part of 'mobile_session_store.dart';

abstract class MobileSessionStore {
  Future<MobileSessionData> load();

  Future<void> save(MobileSessionData data);

  Future<void> clear();
}

class FileMobileSessionStore implements MobileSessionStore {
  FileMobileSessionStore({String? filePath}) : _filePath = filePath;

  static const _channel = MethodChannel('xcagi/session_store');
  final String? _filePath;
  File? _cachedFile;

  @override
  Future<MobileSessionData> load() async {
    final file = await _file();
    if (!await file.exists()) return MobileSessionData.empty;
    final text = await file.readAsString();
    if (text.trim().isEmpty) return MobileSessionData.empty;
    final json = jsonDecode(text);
    if (json is! Map) return MobileSessionData.empty;
    return MobileSessionData.fromJson(
      json.map((key, value) => MapEntry(key.toString(), value)),
    );
  }

  @override
  Future<void> save(MobileSessionData data) async {
    final file = await _file();
    await file.parent.create(recursive: true);
    await file.writeAsString(jsonEncode(data.toJson()), flush: true);
  }

  @override
  Future<void> clear() async {
    final file = await _file();
    if (await file.exists()) await file.delete();
  }

  Future<File> _file() async {
    final cached = _cachedFile;
    if (cached != null) return cached;
    final explicit = _filePath?.trim();
    if (explicit != null && explicit.isNotEmpty) {
      return _cachedFile = File(explicit);
    }
    final path = await _channel.invokeMethod<String>('sessionFilePath');
    final resolved = path?.trim().isNotEmpty == true
        ? path!.trim()
        : '${Directory.systemTemp.path}/xcagi_session.json';
    return _cachedFile = File(resolved);
  }
}

class MemoryMobileSessionStore implements MobileSessionStore {
  MemoryMobileSessionStore([this._data = MobileSessionData.empty]);

  MobileSessionData _data;

  @override
  Future<MobileSessionData> load() async => _data;

  @override
  Future<void> save(MobileSessionData data) async {
    _data = data;
  }

  @override
  Future<void> clear() async {
    _data = MobileSessionData.empty;
  }
}
