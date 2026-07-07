plugins {
    id("com.android.application")
    // The Flutter Gradle Plugin must be applied after the Android and Kotlin Gradle plugins.
    id("dev.flutter.flutter-gradle-plugin")
}

val ssotVersionCodeAnchor = 10

fun devVersionCode(ssotMajor: Int = ssotVersionCodeAnchor): Int =
    (System.currentTimeMillis() / 1000L)
        .coerceAtLeast(ssotMajor.toLong())
        .coerceAtMost(Int.MAX_VALUE.toLong())
        .toInt()

val injectedVersionCode: Int =
    (project.findProperty("androidVersionCode") as String?)?.toIntOrNull()
        ?: System.getenv("XCAGI_ANDROID_VERSION_CODE")?.toIntOrNull()
        ?: devVersionCode()
val injectedVersionName: String =
    (project.findProperty("androidVersionName") as String?)?.takeIf { it.isNotBlank() }
        ?: System.getenv("XCAGI_ANDROID_VERSION_NAME")?.takeIf { it.isNotBlank() }
        ?: "10.0.0"

android {
    namespace = "com.xiuci.xcagi.mobile"
    compileSdk = flutter.compileSdkVersion
    ndkVersion = flutter.ndkVersion

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    defaultConfig {
        applicationId = "com.xiuci.xcagi.mobile"
        minSdk = 26
        targetSdk = 35
        versionCode = injectedVersionCode
        versionName = injectedVersionName
    }

    // 双 SKU 与原生 mobile-android 完全对齐：applicationId 后缀、应用名、PRODUCT_SKU。
    // 构建示例：flutter build apk --flavor enterprise --dart-define=XCAGI_PRODUCT_SKU=enterprise
    flavorDimensions += "sku"
    productFlavors {
        create("personal") {
            dimension = "sku"
            applicationIdSuffix = ".personal"
            resValue("string", "app_name", "XCAGI 个人版")
            buildConfigField("String", "PRODUCT_SKU", "\"personal\"")
        }
        create("enterprise") {
            dimension = "sku"
            applicationIdSuffix = ".enterprise"
            resValue("string", "app_name", "XCAGI 企业版")
            buildConfigField("String", "PRODUCT_SKU", "\"enterprise\"")
        }
    }

    buildFeatures {
        buildConfig = true
        // AGP 新版默认关闭 resValues；flavor 注入 app_name 需要显式开启。
        resValues = true
    }

    buildTypes {
        release {
            // TODO: Add your own signing config for the release build.
            // Signing with the debug keys for now, so `flutter run --release` works.
            signingConfig = signingConfigs.getByName("debug")
        }
    }
}

kotlin {
    compilerOptions {
        jvmTarget = org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17
    }
}

flutter {
    source = "../.."
}

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.biometric:biometric:1.1.0")
    implementation("androidx.datastore:datastore-preferences:1.1.1")
    implementation("androidx.fragment:fragment-ktx:1.8.5")
    implementation("androidx.work:work-runtime-ktx:2.9.1")
}
