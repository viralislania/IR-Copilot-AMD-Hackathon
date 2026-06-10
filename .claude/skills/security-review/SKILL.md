---
name: flutter-security-review
description: Use this skill when implementing authentication, handling user input, working with secrets, creating API integrations, or implementing sensitive mobile features in Flutter. Provides comprehensive Flutter security checklist and patterns.
---

# Flutter Security Review Skill

This skill ensures Flutter applications follow mobile security best practices and identifies potential vulnerabilities specific to the platform.

## When to Activate

- Implementing authentication (Firebase, OAuth2, Biometrics)
- Handling user input via TextFormField or similar
- Integrating with external APIs (http, dio packages)
- Working with secrets or credentials in flutter_secure_storage
- Storing sensitive data locally (SQLite, Hive, local_storage)
- Using WebView to display content
- Handling deep links and app links

## Security Checklist

### 1. Secrets Management

#### FAIL: NEVER Do This
```dart
// Hardcoded secret in code
const String apiKey = '12345-secret-key';

// Hardcoded in environment
class Config {
  static const apiKey = '12345-secret-key';
  static const apiSecret = 'super-secret';
}
```

#### PASS: ALWAYS Do This
```dart
// Use flutter_secure_storage for sensitive data
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

const storage = FlutterSecureStorage();

// Save secret
await storage.write(
  key: 'api_key',
  value: apiKeyFromEnvironment,
);

// Retrieve secret
final apiKey = await storage.read(key: 'api_key');
if (apiKey == null) {
  throw Exception('API key not found');
}

// In build.gradle (Android)
android {
  compileSdkVersion flutter.compileSdkVersion // Prefer the project/default latest stable SDK
  defaultConfig {
    minSdkVersion 21
    // Don't expose secrets here
  }
}

// Use dart-define or CI variables for environment-specific config.
// Treat values bundled into a mobile app as public unless protected by a backend.
```

#### Verification Steps
- [ ] No hardcoded API keys or tokens in code
- [ ] Use `flutter_secure_storage` for all sensitive data
- [ ] Secrets loaded from environment variables (never in code)
- [ ] No secrets committed to version control
- [ ] `.env` files added to `.gitignore`

### 2. Input Validation

#### Always Validate User Input
```dart
import 'package:email_validator/email_validator.dart';

// Email validation
String? validateEmail(String? value) {
  if (value == null || value.isEmpty) {
    return 'Email is required';
  }
  if (!EmailValidator.validate(value)) {
    return 'Please enter a valid email';
  }
  return null;
}

// Username validation
String? validateUsername(String? value) {
  if (value == null || value.isEmpty) {
    return 'Username is required';
  }
  if (value.length < 3 || value.length > 20) {
    return 'Username must be 3-20 characters';
  }
  if (!RegExp(r'^[a-zA-Z0-9_]+$').hasMatch(value)) {
    return 'Username can only contain letters, numbers, and underscores';
  }
  return null;
}

// Using in TextFormField
TextFormField(
  validator: validateEmail,
  onChanged: (value) {
    // Validate on change too
  },
)

// Server-side validation is MANDATORY
Future<void> registerUser(String email, String password) async {
  // Client-side validation
  final emailError = validateEmail(email);
  if (emailError != null) {
    throw ValidationException(emailError);
  }

  // Server must validate again
  final response = await _apiClient.post(
    '/register',
    data: {'email': email, 'password': password},
  );

  if (!response.isSuccess) {
    throw ValidationException(response.message);
  }
}
```

#### Deep Link & Intent Validation
```dart
// lib/app/routes.dart
final GoRouter router = GoRouter(
  routes: [
    GoRoute(
      path: '/user/:id',
      name: 'userDetail',
      builder: (context, state) {
        final id = state.pathParameters['id'];
        
        // Validate ID format
        if (id == null || !isValidUserId(id)) {
          return const InvalidLinkPage();
        }
        
        return UserDetailPage(userId: id);
      },
    ),
  ],
);

bool isValidUserId(String id) {
  // Only allow alphanumeric and hyphens
  return RegExp(r'^[a-zA-Z0-9-]+$').hasMatch(id) && id.length <= 36;
}
```

#### Verification Steps
- [ ] All TextFormField inputs validated with `validator`
- [ ] Regex patterns used for format validation
- [ ] Deep link parameters validated (type, format, length)
- [ ] No direct execution of input as code/commands
- [ ] Server-side validation always implemented (trust nothing from client)

### 3. SQL Injection Prevention

#### FAIL: String Concatenation
```dart
// DANGEROUS - SQL Injection vulnerability
var dbResult = await database.rawQuery(
  "SELECT * FROM users WHERE email = '$userEmail'"
);
```

#### PASS: Use sqflite with Bindings
```dart
import 'package:sqflite/sqflite.dart';

// Use bindings with ?
List<Map> result = await database.rawQuery(
  'SELECT * FROM users WHERE email = ?',
  [userEmail],
);

// Or use the query method
List<Map> result = await database.query(
  'users',
  where: 'email = ?',
  whereArgs: [userEmail],
);
```

#### Using Drift ORM (Recommended)
```dart
import 'package:drift/drift.dart';

@DataClassName('User')
class Users extends Table {
  IntColumn get id => integer().autoIncrement()();
  TextColumn get email => text()();
}

// Query is type-safe and SQL injection proof
final user = await (select(users)
  ..where((tbl) => tbl.email.equals(userEmail)))
  .getSingleOrNull();
```

#### Verification Steps
- [ ] Use ORM (Drift) or parameterized queries
- [ ] Never concatenate user input into queries
- [ ] Use `whereArgs` in sqflite queries
- [ ] No raw SQL unless absolutely necessary

### 4. Authentication & Authorization

#### Secure Token Storage
```dart
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:jwt_decoder/jwt_decoder.dart';

class AuthService {
  static const storage = FlutterSecureStorage();
  static const _tokenKey = 'auth_token';
  static const _refreshTokenKey = 'refresh_token';

  // Save tokens securely
  Future<void> saveTokens(String accessToken, String refreshToken) async {
    await storage.write(key: _tokenKey, value: accessToken);
    await storage.write(key: _refreshTokenKey, value: refreshToken);
  }

  // Retrieve token securely
  Future<String?> getAccessToken() async {
    final token = await storage.read(key: _tokenKey);
    
    if (token == null) return null;
    
    // Check if expired
    if (JwtDecoder.isExpired(token)) {
      await refreshToken();
      return await storage.read(key: _tokenKey);
    }
    
    return token;
  }

  // Refresh token securely
  Future<void> refreshToken() async {
    final refreshToken = await storage.read(key: _refreshTokenKey);
    if (refreshToken == null) throw Exception('Refresh token not found');

    try {
      final response = await _httpClient.post(
        '/auth/refresh',
        data: {'refreshToken': refreshToken},
      );
      
      await saveTokens(
        response.data['accessToken'],
        response.data['refreshToken'],
      );
    } catch (e) {
      await logout();
      rethrow;
    }
  }

  // Clear tokens on logout
  Future<void> logout() async {
    await storage.delete(key: _tokenKey);
    await storage.delete(key: _refreshTokenKey);
  }
}
```

#### Biometric Authentication
```dart
import 'package:local_auth/local_auth.dart';

class BiometricService {
  final LocalAuthentication _auth = LocalAuthentication();

  Future<bool> canAuthenticate() async {
    try {
      return await _auth.canCheckBiometrics ||
          await _auth.deviceSupportsBiometric;
    } catch (e) {
      return false;
    }
  }

  Future<bool> authenticate() async {
    try {
      return await _auth.authenticate(
        localizedReason: 'Authenticate to access your account',
        options: const AuthenticationOptions(
          stickyAuth: true,
          biometricOnly: true, // Force biometric, not passcode
        ),
      );
    } catch (e) {
      return false;
    }
  }
}

// Usage in store
class AuthStore {
  @action
  Future<void> loginWithBiometric() async {
    if (!await _biometricService.authenticate()) {
      error = 'Biometric authentication failed';
      return;
    }

    // Authenticate with server using stored token
    final token = await _authService.getAccessToken();
    if (token != null) {
      await _loadUserProfile();
    }
  }
}
```

#### Verification Steps
- [ ] Tokens stored ONLY in `flutter_secure_storage`
- [ ] Never store tokens in SharedPreferences
- [ ] JWT tokens checked for expiration before use
- [ ] Refresh token mechanism implemented
- [ ] Logout clears all stored credentials
- [ ] Biometric uses `biometricOnly: true`


### Mobile-Specific Security Gaps to Check

These are easy to miss in Flutter reviews:

- **Do not treat bundled API keys as secrets**. Anything shipped in the app can be extracted; move privileged calls behind a backend.
- **Use OAuth2/OIDC with PKCE** for external sign-in flows. Do not embed client secrets in mobile apps.
- **Validate app links and deep links** before routing or fetching data. Reject unknown hosts, schemes, IDs, and redirect targets.
- **Exclude sensitive files from backup** where applicable and clear caches on logout.
- **Use Play Integrity / App Attest / DeviceCheck** for high-risk abuse protection when the backend supports it. Root/jailbreak checks are only risk signals, not sole authorization controls.
- **Redact telemetry and crash reports**. Verify analytics, breadcrumbs, and exception metadata do not include tokens, PII, or request bodies.

### 5. WebView Security

#### Disable Dangerous Features
```dart
import 'package:webview_flutter/webview_flutter.dart';

class SafeWebView extends StatefulWidget {
  final String url;

  const SafeWebView({required this.url});

  @override
  State<SafeWebView> createState() => _SafeWebViewState();
}

class _SafeWebViewState extends State<SafeWebView> {
  late final WebViewController _controller;

  @override
  void initState() {
    super.initState();

    _controller = WebViewController()
      ..setJavaScriptMode(JavaScriptMode.disabled) // Enable only for trusted content that requires it
      ..setNavigationDelegate(
        NavigationDelegate(
          onPageStarted: (String url) {
            // Only allow trusted domains
            if (!_isAllowedUrl(url)) {
              _controller.goBack();
            }
          },
          onWebResourceError: (WebResourceError error) {
            // Handle errors securely
          },
        ),
      )
      ..loadRequest(_validatedUri(widget.url));
  }

  Uri _validatedUri(String url) {
    final uri = Uri.parse(url);
    if (uri.scheme != 'https' || !_isAllowedHost(uri.host)) {
      throw ArgumentError('Blocked untrusted WebView URL');
    }
    return uri;
  }

  bool _isAllowedUrl(String url) {
    final uri = Uri.parse(url);
    return uri.scheme == 'https' && _isAllowedHost(uri.host);
  }

  bool _isAllowedHost(String host) {
    return host == 'trusted.com' || host == 'www.trusted.com';
  }

  @override
  Widget build(BuildContext context) {
    return WebViewWidget(controller: _controller);
  }
}
```

#### Verification Steps
- [ ] Only load from HTTPS URLs
- [ ] Implement URL whitelist for WebView
- [ ] Disable JavaScript if not absolutely necessary
- [ ] Validate all navigation targets
- [ ] No access to sensitive local files

### 6. Network Security

#### Use HTTPS and Certificate Pinning
```dart
import 'package:dio/dio.dart';
import 'package:dio_http_cache/dio_http_cache.dart';

class SecureHttpClient {
  final Dio _dio = Dio();

  SecureHttpClient() {
    _configureDio();
  }

  void _configureDio() {
    // Only allow HTTPS
    _dio.httpClientAdapter = HttpClientAdapter();

    // Add security interceptor
    _dio.interceptors.add(
      InterceptorsWrapper(
        onRequest: (options, handler) {
          // Add security headers
          options.headers['X-Requested-With'] = 'XMLHttpRequest';
          return handler.next(options);
        },
        onError: (error, handler) {
          // Log errors safely (no sensitive data)
          debugPrint('HTTP Error: ${error.response?.statusCode}');
          return handler.next(error);
        },
      ),
    );

    // Certificate pinning (optional but recommended)
    // _setupCertificatePinning();
  }

  Future<Response> get(String path) async {
    return _dio.get(path);
  }

  Future<Response> post(String path, {required dynamic data}) async {
    return _dio.post(path, data: data);
  }
}
```

#### Verification Steps
- [ ] All API calls use HTTPS only
- [ ] Certificate pinning implemented for critical APIs
- [ ] Security headers added (CORS, CSP, etc.)
- [ ] No cleartext HTTP endpoints
- [ ] Request/response logging doesn't expose sensitive data

### 7. Local Storage Security

#### Secure SharedPreferences
```dart
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

// DON'T use SharedPreferences for sensitive data
// Use flutter_secure_storage instead

class SecurePreferences {
  static const storage = FlutterSecureStorage();

  // Store sensitive user data
  static Future<void> setSensitiveData(String key, String value) async {
    await storage.write(key: key, value: value);
  }

  // Read sensitive data
  static Future<String?> getSensitiveData(String key) async {
    return await storage.read(key: key);
  }

  // Clear all sensitive data
  static Future<void> clearAll() async {
    await storage.deleteAll();
  }
}
```

#### Secure Database with Encryption
```dart
import 'package:sqflite/sqflite.dart';
import 'package:sqlite3/sqlite3.dart';

// Enable SQLite encryption if using SqlCipher
Future<Database> openSecureDatabase() async {
  final databasesPath = await getDatabasesPath();
  final path = join(databasesPath, 'app.db');

  return openDatabase(
    path,
    onCreate: (db, version) async {
      // Create tables
    },
    version: 1,
    // Note: SqlCipher support requires native setup
  );
}

// Or use encryption with Drift ORM
import 'package:drift/drift.dart';

final database = AppDatabase.withExecutor(
  // Encrypted executor if needed
);
```

#### Verification Steps
- [ ] Sensitive data stored in `flutter_secure_storage`
- [ ] Database encryption enabled if available
- [ ] No sensitive data in SharedPreferences
- [ ] File permissions properly set
- [ ] Cache cleared on logout

### 8. Sensitive Data Exposure

#### Prevent Screenshots
```dart
import 'package:flutter_windowmanager/flutter_windowmanager.dart';

class SecureScreen extends StatefulWidget {
  @override
  State<SecureScreen> createState() => _SecureScreenState();
}

class _SecureScreenState extends State<SecureScreen> {
  @override
  void initState() {
    super.initState();
    _disableScreenshot();
  }

  void _disableScreenshot() async {
    await FlutterWindowManager.addFlags(FlutterWindowManager.FLAG_SECURE);
  }

  @override
  void dispose() {
    FlutterWindowManager.clearFlags(FlutterWindowManager.FLAG_SECURE);
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Sensitive Data')),
      body: const Center(child: Text('Protected from screenshots')),
    );
  }
}
```

#### Secure Logging
```dart
class Logger {
  static void debug(String message) {
    if (kDebugMode) {
      debugPrint('DEBUG: $message');
    }
  }

  static void logError(Object error, StackTrace? stackTrace) {
    if (kDebugMode) {
      // In debug, log everything
      debugPrint('ERROR: $error');
      debugPrint('$stackTrace');
    } else {
      // In production, log only sanitized info
      debugPrint('ERROR: Error occurred');
      // Send to error tracking without sensitive data
    }
  }

  // NEVER log sensitive data
  static void loginError(String? email, String? reason) {
    // BAD: Logger.debug('Login failed for $email: $reason');
    
    // GOOD:
    if (kDebugMode) {
      debugPrint('Login failed for user');
    }
  }
}
```

#### Verification Steps
- [ ] `FLAG_SECURE` set on sensitive screens
- [ ] No PII or secrets in logs in release builds
- [ ] Error tracking doesn't expose sensitive data
- [ ] Debugprint used only in debug mode
- [ ] ProGuard/R8 enabled for obfuscation

### 9. Permissions (Least Privilege)

#### Runtime Permissions
```dart
import 'package:permission_handler/permission_handler.dart';

class PermissionService {
  // Request only when needed
  Future<bool> requestCameraPermission() async {
    final status = await Permission.camera.request();
    return status.isGranted;
  }

  // Check before using
  Future<bool> hasCameraPermission() async {
    return (await Permission.camera.status).isGranted;
  }

  // Handle denial gracefully
  Future<void> useCamera() async {
    final granted = await requestCameraPermission();
    if (!granted) {
      // Show explanation to user
      _showPermissionDeniedDialog();
      return;
    }

    // Use camera
  }
}

// In AndroidManifest.xml - request only essential permissions
// <uses-permission android:name="android.permission.CAMERA" />
// <uses-permission android:name="android.permission.ACCESS_FINE_LOCATION" />

// In Info.plist (iOS) - provide explanations
// <key>NSCameraUsageDescription</key>
// <string>This app needs camera access to take photos</string>
```

#### Verification Steps
- [ ] Only essential permissions requested in manifest/plist
- [ ] Runtime permissions requested before use
- [ ] Graceful handling of permission denial
- [ ] Explanation provided to user for permissions
- [ ] Permissions reviewed for privacy compliance

### 10. Dependency Security

#### Keep Dependencies Updated
```yaml
# pubspec.yaml
dependencies:
  flutter:
    sdk: flutter
  http: ^1.1.0         # Keep updated
  firebase_core: ^2.20.0
  flutter_secure_storage: ^9.0.0

dev_dependencies:
  test: ^1.24.0
  mockito: ^5.4.0
```

#### Verify No Known Vulnerabilities
```bash
# Check for vulnerable dependencies
flutter pub outdated
flutter pub get

# Use pub.dev to check packages before adding
# Check package popularity and security issues
```

#### Verification Steps
- [ ] Dependencies up to date (run `flutter pub outdated`)
- [ ] No known vulnerabilities in packages used
- [ ] Avoid unmaintained or suspicious packages
- [ ] Lock files committed for reproducible builds
- [ ] Review third-party package permissions

## Best Practices Summary

1. **Trust Nothing**: Assume device could be compromised. Validate on server.
2. **Encrypt Sensitive Data**: Use `flutter_secure_storage` for secrets and tokens
3. **Validate Input**: Client-side for UX, server-side for security
4. **Handle Errors Safely**: Don't expose sensitive info in error messages
5. **Log Carefully**: Remove sensitive data from logs in production
6. **Use HTTPS**: Always, everywhere, no exceptions
7. **Dispose Properly**: Close streams, clear sensitive data on logout
8. **Test Security**: Include security tests in your test suite

## Security Testing Checklist

- [ ] Verify tokens stored securely and not in logs
- [ ] Test input validation (SQL injection, XSS)
- [ ] Verify SSL certificate validation
- [ ] Test logout clears all sensitive data
- [ ] Verify deep links validate all parameters
- [ ] Test error handling doesn't leak sensitive info
- [ ] Verify biometric/auth flow cannot be bypassed
- [ ] Check no hardcoded secrets in code or assets
