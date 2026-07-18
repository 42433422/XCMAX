# Flutter Android Runner rules for platform background workers (WorkManager +
# Room). Without these keeps the release
# R8 build strips WorkDatabase and the app crashes at startup with
# "Failed to create an instance of class androidx.work.impl.WorkDatabase".

# --- WorkManager ---
-keep class androidx.work.** { *; }
-keep class * extends androidx.work.Worker
-keep class * extends androidx.work.CoroutineWorker
-keep class * extends androidx.work.ListenableWorker
-dontwarn androidx.work.**

# --- Room (WorkManager's WorkDatabase is a RoomDatabase) ---
-keep class * extends androidx.room.RoomDatabase
-keep @androidx.room.Entity class *
-keep class * implements androidx.room.Dao
-keep @androidx.room.Dao class *
-keepclassmembers class * {
    @androidx.room.* <methods>;
    @androidx.room.* <fields>;
}
-dontwarn androidx.room.**

# --- androidx.startup (WorkManagerInitializer runs via InitializationProvider) ---
-keep class androidx.startup.** { *; }

# --- App workers invoked reflectively by WorkManager ---
-keep class com.xiuci.xcagi.mobile.** { *; }
