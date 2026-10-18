-- Two roles: the owner runs migrations; the app role gets least privilege (no UPDATE/DELETE on audit).
CREATE ROLE itp_owner LOGIN PASSWORD 'itp_owner';
CREATE ROLE itp_app LOGIN PASSWORD 'itp_app';
CREATE DATABASE itp OWNER itp_owner;
CREATE DATABASE itp_test OWNER itp_owner;
