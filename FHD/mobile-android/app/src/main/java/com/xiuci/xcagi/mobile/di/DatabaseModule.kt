package com.xiuci.xcagi.mobile.di

import android.content.Context
import androidx.room.Room
import com.xiuci.xcagi.mobile.core.db.XcagiDatabase
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.android.qualifiers.ApplicationContext
import dagger.hilt.components.SingletonComponent
import javax.inject.Singleton

@Module
@InstallIn(SingletonComponent::class)
object DatabaseModule {
    @Provides
    @Singleton
    fun provideDb(@ApplicationContext ctx: Context): XcagiDatabase =
        Room.databaseBuilder(ctx, XcagiDatabase::class.java, "xcagi.db")
            .addMigrations(
                XcagiDatabase.MIGRATION_3_4,
                XcagiDatabase.MIGRATION_4_5,
                XcagiDatabase.MIGRATION_5_6,
                XcagiDatabase.MIGRATION_6_7,
                XcagiDatabase.MIGRATION_7_8,
                XcagiDatabase.MIGRATION_8_9,
            )
            .build()
}
