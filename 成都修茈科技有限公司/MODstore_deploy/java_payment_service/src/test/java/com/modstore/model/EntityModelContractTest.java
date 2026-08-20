package com.modstore.model;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.lang.reflect.Modifier;
import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.Arrays;
import java.util.List;
import org.junit.jupiter.api.Test;

/**
 * Verifies the persistence models as JavaBean value objects.
 *
 * <p>These checks intentionally exercise every generated accessor and every field in Lombok's
 * equals/hashCode/toString implementation. Besides protecting ORM binding, this catches a subtle
 * regression where adding a field to an entity without rebuilding its generated value contract can
 * make equality-based idempotency checks silently ignore that field.
 */
class EntityModelContractTest {

    private static final List<Class<?>> ENTITY_TYPES = List.of(
            AccountExperienceLedger.class,
            CatalogItem.class,
            Entitlement.class,
            Order.class,
            PlanTemplate.class,
            Purchase.class,
            Quota.class,
            Refund.class,
            Transaction.class,
            User.class,
            UserPlan.class,
            Wallet.class,
            WalletHold.class);

    @Test
    void generatedBeanAndValueContractsCoverEveryPersistentField() throws Exception {
        for (Class<?> entityType : ENTITY_TYPES) {
            verifyEntityContract(entityType);
        }
    }

    private static void verifyEntityContract(Class<?> entityType) throws Exception {
        List<Field> fields = persistentFields(entityType);
        Object populated = entityType.getDeclaredConstructor().newInstance();
        Object equalCopy = entityType.getDeclaredConstructor().newInstance();

        for (int index = 0; index < fields.size(); index++) {
            Field field = fields.get(index);
            Object value = sampleValue(field.getType(), field.getName(), index, false);
            setter(entityType, field).invoke(populated, value);
            setter(entityType, field).invoke(equalCopy, value);
            assertEquals(value, getter(entityType, field).invoke(populated),
                    () -> entityType.getSimpleName() + "." + field.getName());
        }

        assertEquals(populated, populated);
        assertEquals(populated, equalCopy);
        assertEquals(populated.hashCode(), equalCopy.hashCode());
        assertNotNull(populated.toString());
        assertFalse(populated.toString().isBlank());
        assertNotEquals(populated, null);
        assertNotEquals(populated, new Object());

        // Lombok compares fields in declaration order. Keep all preceding values equal so each
        // generated comparison (including its null branches) is reached at least once.
        for (int differingIndex = 0; differingIndex < fields.size(); differingIndex++) {
            Object left = entityType.getDeclaredConstructor().newInstance();
            Object right = entityType.getDeclaredConstructor().newInstance();
            for (int index = 0; index <= differingIndex; index++) {
                Field field = fields.get(index);
                Object common = sampleValue(field.getType(), field.getName(), index, false);
                setter(entityType, field).invoke(left, common);
                setter(entityType, field).invoke(
                        right,
                        index == differingIndex
                                ? sampleValue(field.getType(), field.getName(), index, true)
                                : common);
            }
            Field field = fields.get(differingIndex);
            assertNotEquals(left, right,
                    () -> entityType.getSimpleName() + "." + field.getName());

            if (!field.getType().isPrimitive()) {
                Object nullLeft = entityType.getDeclaredConstructor().newInstance();
                Object nullRight = entityType.getDeclaredConstructor().newInstance();
                for (int index = 0; index < differingIndex; index++) {
                    Field preceding = fields.get(index);
                    Object common = sampleValue(
                            preceding.getType(), preceding.getName(), index, false);
                    setter(entityType, preceding).invoke(nullLeft, common);
                    setter(entityType, preceding).invoke(nullRight, common);
                }
                setter(entityType, field).invoke(
                        nullRight,
                        sampleValue(field.getType(), field.getName(), differingIndex, false));
                assertNotEquals(nullLeft, nullRight);
                assertNotEquals(nullRight, nullLeft);
            }
        }
    }

    private static List<Field> persistentFields(Class<?> entityType) {
        return Arrays.stream(entityType.getDeclaredFields())
                .filter(field -> !Modifier.isStatic(field.getModifiers()))
                .toList();
    }

    private static Method setter(Class<?> entityType, Field field) throws NoSuchMethodException {
        return entityType.getMethod("set" + capitalize(field.getName()), field.getType());
    }

    private static Method getter(Class<?> entityType, Field field) throws NoSuchMethodException {
        String prefix = field.getType() == boolean.class ? "is" : "get";
        return entityType.getMethod(prefix + capitalize(field.getName()));
    }

    private static String capitalize(String value) {
        return Character.toUpperCase(value.charAt(0)) + value.substring(1);
    }

    private static Object sampleValue(
            Class<?> type, String fieldName, int index, boolean alternate) throws Exception {
        int offset = alternate ? 10_000 : 0;
        if (type == String.class) {
            return fieldName + "-" + (index + offset);
        }
        if (type == Long.class || type == long.class) {
            return (long) index + 1L + offset;
        }
        if (type == int.class) {
            return index + 1 + offset;
        }
        if (type == boolean.class) {
            return !alternate;
        }
        if (type == BigDecimal.class) {
            return BigDecimal.valueOf(index + 1L + offset, 2);
        }
        if (type == LocalDateTime.class) {
            return LocalDateTime.of(2026, 1, 1, 0, 0).plusSeconds(index + offset);
        }
        Object relation = type.getDeclaredConstructor().newInstance();
        if (alternate) {
            persistentFields(type).stream()
                    .filter(field -> isScalar(field.getType()))
                    .findFirst()
                    .ifPresent(field -> {
                        try {
                            setter(type, field).invoke(
                                    relation,
                                    sampleValue(field.getType(), field.getName(), index, true));
                        } catch (Exception exception) {
                            throw new IllegalStateException(exception);
                        }
                    });
        }
        return relation;
    }

    private static boolean isScalar(Class<?> type) {
        return type == String.class
                || type == Long.class
                || type == long.class
                || type == int.class
                || type == boolean.class
                || type == BigDecimal.class
                || type == LocalDateTime.class;
    }
}
