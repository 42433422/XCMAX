part of 'mobile_repository.dart';

abstract class _RepoBusinessBase extends _RepoServicesBase {
  Future<List<BusinessListItem>> loadCustomers() async {
    final response = await _client.customers();
    if (!response.success) {
      throw MobileRepositoryException(response.message.ifEmpty('客户加载失败'));
    }
    return _businessItemsFromData(response.data);
  }

  Future<List<BusinessListItem>> loadShipments() async {
    final response = await _client.shipments();
    if (!response.success) {
      throw MobileRepositoryException(response.message.ifEmpty('发货加载失败'));
    }
    return _businessItemsFromData(response.data);
  }

  Future<List<BusinessListItem>> loadInventory() async {
    final body = await _client.inventoryItems();
    final data = _nestedDataMap(body);
    final rows = _firstObjectList([
      data['items'],
      data['data'],
      data['results'],
    ]);
    if (rows.isNotEmpty) {
      return rows.map(BusinessListItem.fromJson).toList(growable: false);
    }
    final raw = data['items'] ?? data['data'];
    if (raw is List) {
      return raw
          .map(
            (item) => BusinessListItem(
              id: item.toString(),
              title: item.toString(),
              subtitle: '',
            ),
          )
          .toList(growable: false);
    }
    return const <BusinessListItem>[];
  }

  Future<List<BusinessListItem>> loadBridgeRequests({
    String? status,
    String? requestType,
  }) async {
    try {
      final response = await _client.bridgeRequests(
        status: status,
        requestType: requestType,
      );
      if (!response.success) {
        throw MobileRepositoryException(
          response.message.ifEmpty('移动端服务桥接请求列表加载失败'),
        );
      }
      return _bridgeItemsFromData(response.data);
    } on MobileApiException catch (error) {
      if (error.statusCode != 404) rethrow;
      final legacy = await _client.legacyBridgeRequests(
        status: status,
        requestType: requestType,
      );
      return _bridgeItemsFromData(_nestedDataMap(legacy));
    }
  }

  Future<void> respondBridgeRequest({
    required int id,
    required String response,
    String respondedBy = 'android',
  }) async {
    final text = response.trim();
    if (id <= 0) {
      throw const MobileRepositoryException('请先选择工单');
    }
    if (text.isEmpty) {
      throw const MobileRepositoryException('回复不能为空');
    }
    try {
      final result = await _client.bridgeRespond(
        id: id,
        response: text,
        respondedBy: respondedBy,
      );
      if (!result.success) {
        throw MobileRepositoryException(result.message.ifEmpty('回复失败'));
      }
    } on MobileApiException catch (error) {
      if (error.statusCode != 404) rethrow;
      await _client.legacyBridgeRespond(
        id: id,
        response: text,
        respondedBy: respondedBy,
      );
    }
  }

  Future<String> loadFinanceSummary() async {
    final body = await _client.financeSummary();
    return body.toString();
  }

}
