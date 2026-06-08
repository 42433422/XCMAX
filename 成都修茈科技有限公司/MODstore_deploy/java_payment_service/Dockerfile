FROM maven:3.9-eclipse-temurin-17 AS build

WORKDIR /workspace
COPY pom.xml ./
COPY src ./src
# 单次 package 拉依赖；不单独 go-offline，避免 Central SSL 偶发失败时多占一层失败面
RUN mvn -q -DskipTests package

FROM eclipse-temurin:17-jre-alpine

WORKDIR /app
RUN apk add --no-cache curl
COPY --from=build /workspace/target/*.jar /app/payment-service.jar

EXPOSE 8080

CMD ["java", "-jar", "/app/payment-service.jar"]
