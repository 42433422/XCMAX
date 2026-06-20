# ============================================================================
# XCAGI Android ProGuard / R8 规则
# 维护说明:新增依赖后,若 release 构建崩溃,优先在此补 keep 规则
# ============================================================================

# --- 基础:保留源文件名与行号,便于 Crashlytics 符号化 ---
-keepattributes SourceFile,LineNumberTable
-renamesourcefileattribute SourceFile
-keepattributes RuntimeVisibleAnnotations,RuntimeVisibleParameterAnnotations,RuntimeInvisibleAnnotations,RuntimeInvisibleParameterAnnotations
-keepattributes Signature,InnerClasses,EnclosingMethod,Deprecated,Exceptions
-keepattributes AnnotationDefault

# --- Kotlin 元数据与协程 ---
-keep class kotlin.Metadata { *; }
-keepclassmembers class kotlinx.** { *; }
-dontwarn kotlinx.coroutines.**
-keep class kotlinx.coroutines.android.AndroidExceptionPreHandler { *; }
-keep class kotlinx.coroutines.android.AndroidDispatcherFactory { *; }

# --- 项目模型与网络层(契约生成 + Retrofit 接口) ---
-keep class com.xiuci.xcagi.mobile.core.model.** { *; }
-keep class com.xiuci.xcagi.mobile.core.network.** { *; }
-keep class com.xiuci.xcagi.mobile.api.contract.** { *; }

# --- Retrofit ---
-keepclasseswithmembers class * {
    @retrofit2.http.* <methods>;
}
-keep,allowobfuscation,allowshrinking interface retrofit2.Call
-keep,allowobfuscation,allowshrinking class retrofit2.Response
-keep,allowobfuscation,allowshrinking class kotlin.coroutines.Continuation

# --- OkHttp ---
-dontwarn okhttp3.**
-dontwarn okio.**
-dontwarn org.conscrypt.**
-dontwarn org.bouncycastle.**
-dontwarn org.openjsse.**

# --- Gson ---
-keep class com.google.gson.** { *; }
-keep class * extends com.google.gson.TypeAdapter
-keep class * implements com.google.gson.TypeAdapterFactory
-keep class * implements com.google.gson.JsonSerializer
-keep class * implements com.google.gson.JsonDeserializer
-keepclassmembers,allowobfuscation class * {
    @com.google.gson.annotations.SerializedName <fields>;
}

# --- Hilt / Dagger(必须保留,否则 release 注入失败) ---
-keep class dagger.hilt.** { *; }
-keep class javax.inject.** { *; }
-keep class * extends dagger.hilt.android.HiltAndroidApp
-keep @dagger.hilt.android.HiltAndroidApp class *
-keep @dagger.hilt.android.lifecycle.HiltViewModel class *
-keepclassmembers class * {
    @dagger.hilt.android.lifecycle.HiltViewModel <init>(...);
}
-keep class * extends dagger.hilt.android.internal.lifecycle.HiltViewModelFactory$ViewModelComponentBuilderEntryPoint
-keep,allowobfuscation,allowshrinking class * extends dagger.hilt.android.internal.modules.ApplicationContextModule
-dontwarn dagger.hilt.**

# --- Room(必须保留 DAO 与实体,否则运行时 NPE) ---
-keep class * extends androidx.room.RoomDatabase
-keep @androidx.room.Entity class *
-keep class * implements androidx.room.Dao
-keep @androidx.room.Dao class *
-keepclassmembers class * {
    @androidx.room.* <methods>;
    @androidx.room.* <fields>;
}
-dontwarn androidx.room.**

# --- Compose(一般 R8 默认规则够用,补关键类) ---
-dontwarn androidx.compose.**
-keep class androidx.compose.runtime.** { *; }

# --- Coroutines Flow(状态流序列化) ---
-keepclassmembers class kotlinx.coroutines.flow.** { *; }

# --- DataStore ---
-keep class androidx.datastore.** { *; }
-dontwarn androidx.datastore.**

# --- WorkManager + Hilt-Work ---
-keep class androidx.work.** { *; }
-keep class * extends androidx.work.Worker
-keep class * extends androidx.work.CoroutineWorker
-keep class * extends androidx.work.ListenableWorker
-keepclassmembers class * {
    @dagger.hilt.android.HiltWorker <init>(...);
}

# --- Navigation Compose ---
-keep class androidx.navigation.** { *; }
-dontwarn androidx.navigation.**

# --- Coil ---
-dontwarn coil.**

# --- Firebase ---
-keep class com.google.firebase.** { *; }
-keep class com.google.android.gms.** { *; }
-dontwarn com.google.firebase.**

# --- JPush / 极光 ---
-keep class cn.jpush.** { *; }
-keep class cn.jiguang.** { *; }
-dontwarn cn.jpush.**
-dontwarn cn.jiguang.**

# --- ML Kit(条码扫描) ---
-keep class com.google.mlkit.** { *; }
-dontwarn com.google.mlkit.**

# --- CameraX ---
-keep class androidx.camera.** { *; }
-dontwarn androidx.camera.**

# --- Biometric ---
-keep class androidx.biometric.** { *; }
-dontwarn androidx.biometric.**

# --- Security Crypto ---
-keep class androidx.security.crypto.** { *; }
-dontwarn androidx.security.crypto.**

# --- WebKit / Browser ---
-keep class androidx.webkit.** { *; }
-keep class androidx.browser.** { *; }
