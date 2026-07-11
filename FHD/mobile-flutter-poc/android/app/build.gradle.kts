import java.io.File
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
            val localPropsFile = rootProject.file("keystore.properties")
            val nativePropsFile = rootProject.file("../../mobile-android/keystore.properties")
            val propsFile = when {
                localPropsFile.isFile -> localPropsFile
                nativePropsFile.isFile -> nativePropsFile
                else -> localPropsFile
            }
            val keystoreProps = Properties()
            if (propsFile.isFile) {
                propsFile.inputStream().use { keystoreProps.load(it) }
            }

            fun property(name: String, key: String): String? =
                System.getenv(name)?.trim()?.takeIf { it.isNotEmpty() }
                    ?: keystoreProps.getProperty(key)?.trim()?.takeIf { it.isNotEmpty() }

            val envStorePath = System.getenv("XCAGI_ANDROID_KEYSTORE")
                ?.trim()
                ?.takeIf { it.isNotEmpty() }
            val storePath = envStorePath
                ?: keystoreProps.getProperty("storeFile")?.trim()?.takeIf { it.isNotEmpty() }
            if (storePath != null) {
                val configuredFile = File(storePath)
                val resolved = when {
                    configuredFile.isAbsolute -> configuredFile
                    envStorePath != null -> rootProject.file(storePath)
                    else -> File(propsFile.parentFile, storePath)
                }
                if (!resolved.isFile) {
                    throw GradleException("Release keystore not found: ${resolved.absolutePath}")
                }
                storeFile = resolved
                storePassword = property("XCAGI_ANDROID_KEYSTORE_PASSWORD", "storePassword")
                keyAlias = property("XCAGI_ANDROID_KEY_ALIAS", "keyAlias")
                keyPassword = property("XCAGI_ANDROID_KEY_PASSWORD", "keyPassword")
                    ?: storePassword
                if (storePassword.isNullOrBlank() || keyAlias.isNullOrBlank()) {
                    throw GradleException(
                        "Release signing incomplete: configure keystore password and alias via " +
                            "keystore.properties or XCAGI_ANDROID_* environment variables.",
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
            if (releaseSigning.storeFile != null) {
                signingConfig = releaseSigning
            }
        }
    }
}

tasks.matching {
    (it.name.startsWith("assemble") || it.name.startsWith("bundle")) &&
        it.name.contains("Release")
}.configureEach {
    doFirst {
        val releaseSigning = android.signingConfigs.getByName("release")
        if (releaseSigning.storeFile == null) {
            throw GradleException(
                "XCAGI Flutter Release requires production signing. Configure " +
                    "keystore.properties or XCAGI_ANDROID_* secrets; debug-signed release " +
                    "artifacts are forbidden.",
            )
        }
        logger.lifecycle("XCAGI Flutter Release: production signing configured")
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
    testImplementation("junit:junit:4.13.2")
}
