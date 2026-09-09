package com.modstore;

import org.flywaydb.core.Flyway;
import org.flywaydb.core.internal.database.DatabaseTypeRegister;
import org.junit.jupiter.api.Test;

import java.sql.Connection;
import java.sql.DatabaseMetaData;
import java.sql.PreparedStatement;
import java.sql.ResultSet;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;
import static org.mockito.ArgumentMatchers.anyString;

class FlywayPostgresRuntimeTest {
    @Test
    void discoversPostgresModuleForProductionDatabase() throws Exception {
        Connection connection = mock(Connection.class);
        DatabaseMetaData metadata = mock(DatabaseMetaData.class);
        when(connection.getMetaData()).thenReturn(metadata);
        when(metadata.getDatabaseProductName()).thenReturn("PostgreSQL");
        when(metadata.getDatabaseProductVersion()).thenReturn("10.23");
        when(metadata.getDatabaseMajorVersion()).thenReturn(10);
        when(metadata.getDatabaseMinorVersion()).thenReturn(23);
        PreparedStatement statement = mock(PreparedStatement.class);
        ResultSet result = mock(ResultSet.class);
        when(connection.prepareStatement(anyString())).thenReturn(statement);
        when(statement.executeQuery()).thenReturn(result);
        when(result.next()).thenReturn(true, false);
        when(result.getString(1)).thenReturn("PostgreSQL 10.23");

        assertThat(DatabaseTypeRegister.getDatabaseTypeForConnection(
                connection, Flyway.configure()).getName()).isEqualTo("PostgreSQL");
    }
}
