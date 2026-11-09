# CertiFind backend image. The same image runs the API (SPRING_PROFILES_ACTIVE=prod)
# and the CSV importer (SPRING_PROFILES_ACTIVE=import); see deploy/docker-compose.prod.yml.

FROM maven:3.9-eclipse-temurin-21 AS build
WORKDIR /src
# Dependencies first, so code changes do not re-download them.
COPY pom.xml .
RUN mvn -q -B dependency:go-offline
COPY src src
# Tests need a loaded database, so they run in development, not in the image build.
RUN mvn -q -B package -DskipTests

FROM eclipse-temurin:21-jre
WORKDIR /app
RUN useradd --system --no-create-home certifind
COPY --from=build /src/target/certifind-backend-*.jar app.jar
USER certifind
EXPOSE 8080
ENTRYPOINT ["java", "-jar", "/app/app.jar"]
