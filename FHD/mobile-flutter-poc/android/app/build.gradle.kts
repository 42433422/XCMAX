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
        ?: "1.0.0.1"

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
            // Flutter 惯例 key.properties；同时兼容既有 keystore.properties
            listOf(
                rootProject.file("key.properties"),
                rootProject.file("keystore.properties"),
                project.file("key.properties"),
                project.file("keystore.properties"),
            ).firstOrNull { it.isFile }?.inputStream()?.use { keystoreProps.load(it) }

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
                val resolved =
                    rootProject.file(storePath).takeIf { it.isFile }
                        ?: project.file(storePath)
                if (!resolved.isFile) {
                    throw GradleException("Release keystore not found: ${resolved.absolutePath}")
                }
                storeFile = resolved
                storePassword = prop("KEYSTORE_PASSWORD")
                keyAlias = prop("KEY_ALIAS")
                keyPassword = prop("KEY_PASSWORD") ?: prop("KEYSTORE_PASSWORD")
                if (storePassword.isNullOrBlank() || keyAlias.isNullOrBlank()) {
                    throw GradleException(
                        "Release signing incomplete: set storePassword/keyAlias in key.properties " +
                            "or XCAGI_ANDROID_KEYSTORE* env vars.",
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
                        "Copy android/key.properties.example → key.properties or set XCAGI_ANDROID_KEYSTORE*.",
                )
                else -> signingConfigs.getByName("debug")
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
