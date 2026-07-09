import java.util.Properties

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
        applicationId = "com.xiuci.xcagi.mobile.enterprise"
        minSdk = 26
        targetSdk = 35
        versionCode = injectedVersionCode
        versionName = injectedVersionName
    }

    signingConfigs {
        create("release") {
            val keystoreProps = Properties()
            // Prefer Flutter-local key.properties; fall back to archived mobile-android SSOT.
            val candidates = listOf(
                rootProject.file("key.properties"),
                rootProject.file("../key.properties"),
                rootProject.file("../../mobile-android/keystore.properties"),
            )
            val propsFile = candidates.firstOrNull { it.isFile }
            if (propsFile != null) {
                propsFile.inputStream().use { keystoreProps.load(it) }
            }

            fun prop(name: String): String? =
                System.getenv("XCAGI_ANDROID_${name.uppercase()}")?.takeIf { it.isNotBlank() }
                    ?: keystoreProps.getProperty(
                        when (name) {
                            "KEYSTORE" -> "storeFile"
                            "KEYSTORE_PASSWORD" -> "storePassword"
                            "KEY_ALIAS" -> "keyAlias"
                            "KEY_PASSWORD" -> "keyPassword"
                            else -> name
                        },
                    )?.trim()?.takeIf { it.isNotBlank() }

            val storePath = prop("KEYSTORE")
            if (!storePath.isNullOrBlank()) {
                val fromProps = propsFile?.parentFile?.resolve(storePath)
                val fromAndroidRoot = rootProject.file(storePath)
                val fromMobileAndroid = rootProject.file("../../mobile-android/$storePath")
                val resolved = listOfNotNull(fromProps, fromAndroidRoot, fromMobileAndroid)
                    .firstOrNull { it.isFile }
                    ?: throw GradleException(
                        "Release keystore not found for storeFile=$storePath " +
                            "(checked beside keystore.properties and mobile-android/).",
                    )
                storeFile = resolved
                storePassword = prop("KEYSTORE_PASSWORD")
                keyAlias = prop("KEY_ALIAS")
                keyPassword = prop("KEY_PASSWORD") ?: prop("KEYSTORE_PASSWORD")
                if (storePassword.isNullOrBlank() || keyAlias.isNullOrBlank()) {
                    throw GradleException(
                        "Release signing incomplete: set storePassword and keyAlias " +
                            "in key.properties / mobile-android/keystore.properties or XCAGI_ANDROID_* env.",
                    )
                }
            }
        }
    }

    buildTypes {
        release {
            // Keep WorkManager/Room classes used by the Kotlin background
            // workers; R8 otherwise strips WorkDatabase and the release app
            // crashes on launch inside androidx.startup.InitializationProvider.
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro",
            )
            val releaseSigning = signingConfigs.getByName("release")
            val requireSigning = System.getenv("XCAGI_REQUIRE_RELEASE_SIGNING") == "1"
            signingConfig = when {
                releaseSigning.storeFile != null -> releaseSigning
                requireSigning -> throw GradleException(
                    "XCAGI_REQUIRE_RELEASE_SIGNING=1 but no release keystore configured. " +
                        "Copy mobile-android/keystore.properties or set XCAGI_ANDROID_* env vars.",
                )
                else -> {
                    logger.warn(
                        "XCAGI Flutter release: no keystore found; signing with debug keys. " +
                            "Set mobile-android/keystore.properties for production.",
                    )
                    signingConfigs.getByName("debug")
                }
            }
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
