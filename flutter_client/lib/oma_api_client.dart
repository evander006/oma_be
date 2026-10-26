import 'dart:convert';
import 'package:http/http.dart' as http;

/// Lightweight REST client for the OMA Dom backend.
/// Drop into the Flutter app and adapt to existing models/cubits.
class OmaApiClient {
  OmaApiClient({
    required this.baseUrl,
    http.Client? httpClient,
  }) : _client = httpClient ?? http.Client();

  /// e.g. http://10.0.2.2:8000  (Android emulator)
  final String baseUrl;
  final http.Client _client;

  /// MVP: no authentication — backend always uses demo user Анна.
  Map<String, String> get _headers => {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
      };

  Uri _u(String path, [Map<String, String>? query]) =>
      Uri.parse('$baseUrl$path').replace(queryParameters: query);

  Future<Map<String, dynamic>> health() async {
    final res = await _client.get(_u('/api/v1/health'), headers: _headers);
    return jsonDecode(res.body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> products({
    String? q,
    String? categoryId,
    double? minPrice,
    double? maxPrice,
    String sort = 'name',
    int page = 1,
    int pageSize = 20,
  }) async {
    final query = <String, String>{
      'sort': sort,
      'page': '$page',
      'page_size': '$pageSize',
      if (q != null) 'q': q,
      if (categoryId != null) 'category_id': categoryId,
      if (minPrice != null) 'min_price': '$minPrice',
      if (maxPrice != null) 'max_price': '$maxPrice',
    };
    final res = await _client.get(_u('/api/v1/products', query), headers: _headers);
    _ensureOk(res);
    return jsonDecode(res.body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> product(String id) async {
    final res = await _client.get(_u('/api/v1/products/$id'), headers: _headers);
    _ensureOk(res);
    return jsonDecode(res.body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> aiChat({
    required String message,
    int? sessionId,
    int? roomId,
    List<int> photoIds = const [],
    double? budget,
    String? style,
  }) async {
    final res = await _client.post(
      _u('/api/v1/ai/chat'),
      headers: _headers,
      body: jsonEncode({
        'message': message,
        'session_id': sessionId,
        'room_id': roomId,
        'photo_ids': photoIds,
        'budget': budget,
        'style': style,
      }),
    );
    _ensureOk(res);
    return jsonDecode(res.body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> recommendationsFromRoom({
    required int roomId,
    String prompt = '',
    List<int> photoIds = const [],
    double? maxBudget,
    String? preferredStyle,
    List<String> categoryIds = const [],
    int limit = 6,
  }) async {
    final res = await _client.post(
      _u('/api/v1/ai/recommendations/from-room'),
      headers: _headers,
      body: jsonEncode({
        'room_id': roomId,
        'prompt': prompt,
        'photo_ids': photoIds,
        'max_budget': maxBudget,
        'preferred_style': preferredStyle,
        'category_ids': categoryIds,
        'limit': limit,
      }),
    );
    _ensureOk(res);
    return jsonDecode(res.body) as Map<String, dynamic>;
  }

  void _ensureOk(http.Response res) {
    if (res.statusCode < 200 || res.statusCode >= 300) {
      throw Exception('API ${res.statusCode}: ${res.body}');
    }
  }
}
