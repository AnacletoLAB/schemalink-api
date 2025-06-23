CREATE TABLE Users (
username VARCHAR(50) PRIMARY KEY,
email VARCHAR(255) NOT NULL,
password VARCHAR(255) NOT NULL,
firstName VARCHAR(20) NOT NULL,
lastName VARCHAR(20) NOT NULL,
birthDate DATE NOT NULL,
status VARCHAR(8) NOT NULL CHECK (status IN ('pending', 'active', 'disabled', 'blocked'))
);

CREATE TABLE Policy (
name VARCHAR(8) PRIMARY KEY CHECK (name IN ('trial', 'silver', 'gold', 'platinum')),
maxAccess INT,
threshold INT
);

CREATE TABLE Operation (
name VARCHAR(50) PRIMARY KEY,
target VARCHAR(8) CHECK (target IN ('class', 'relation', 'subgraph')),
description VARCHAR(100) NOT NULL
);

CREATE TABLE Category (
name VARCHAR(13) PRIMARY KEY CHECK (name IN ('add', 'fix', 'reification', 'explain',
'openGPTDialog', 'generate'))
);

CREATE TABLE UserSubscribesPolicy (
username VARCHAR(50) REFERENCES Users(username) ON DELETE CASCADE,
startDate TIMESTAMPTZ,
endDate TIMESTAMPTZ,
requestDate TIMESTAMPTZ,
status VARCHAR(8) NOT NULL CHECK (status IN ('pending', 'active', 'rejected', 'expired')),
numOperations INT,
policyName VARCHAR(8) NOT NULL CHECK (policyName IN ('trial', 'silver', 'gold', 'platinum')) REFERENCES Policy(name) ON DELETE RESTRICT,
PRIMARY KEY (username, requestDate)
);

CREATE TABLE UserMadeOperation (
username VARCHAR(50) REFERENCES Users(username) ON DELETE CASCADE,
date TIMESTAMPTZ,
operationName VARCHAR(50) NOT NULL REFERENCES Operation(name) ON DELETE RESTRICT,
PRIMARY KEY (username, date)
);

CREATE TABLE OperationIsCategory (
operationName VARCHAR(50) REFERENCES Operation(name) ON DELETE CASCADE,
categoryName VARCHAR(13) REFERENCES Category(name) ON DELETE RESTRICT CHECK
(categoryName IN ('add', 'fix', 'reification', 'explain', 'openGPTDialog', 'generate')),
PRIMARY KEY (operationName, categoryName)
);

CREATE TABLE PolicyAllowsCategory (
policyName VARCHAR(8) CHECK (policyName IN ('trial', 'silver', 'gold', 'platinum')) REFERENCES
Policy(name) ON DELETE CASCADE,
categoryName VARCHAR(13) REFERENCES Category(name) ON DELETE RESTRICT CHECK
(categoryName IN ('add', 'fix', 'reification', 'explain', 'openGPTDialog', 'generate')),
PRIMARY KEY (policyName, categoryName)
);




INSERT INTO Policy (name, maxAccess, threshold)
VALUES
('trial', 10, 3),
('silver', 50, 10),
('gold', 100, 15),
('platinum', null, null);

INSERT INTO Operation (name, target, description)
VALUES
('AddClassSimilarToClass', 'class', 'add a new class semantically similar to another class'),
('AddClassAssociatedToClass', 'class', 'add a new class in relation with another class'),
('AddAttributeToRelationship', 'relation', 'add relevant attributes to a relationship'),
('AddClassesSimilarToEntities', 'subgraph', 'add one or more new classes that semantically fit the context
defined by subgraph'),
('ReifyClass', 'class', 'create a class for representing the instance of a class'),
('ExplainClass', 'class', 'explain in human-friendly terms the role of class in the schema'),
('ExplainEntities', 'subgraph', 'explain in human-friendly terms the role of a portion of the schema in the
schema'),
('FixClassName', 'class', 'rename a class'),
('FixClassOntology', 'class', 'enhance the relevant ontologies for a class'),
('FixRelationshipCardinality', 'relation', 'fix cardinality for a relationship'),
('OpenGPTDialog', NULL, 'openGPTDialog'),
('Generate', NULL, 'generate');

INSERT INTO Category (name)
VALUES
('add'),
('fix'),
('reification'),
('explain'),
('openGPTDialog'),
('generate');

INSERT INTO OperationIsCategory (operationName, categoryName)
VALUES
('AddClassSimilarToClass', 'add'),
('AddClassAssociatedToClass', 'add'),
('AddAttributeToRelationship', 'add'),
('AddClassesSimilarToEntities', 'add'),
('ReifyClass', 'reification'),
('ExplainClass', 'explain'),
('ExplainEntities', 'explain'),
('FixClassName', 'fix'),
('FixClassOntology', 'fix'),
('FixRelationshipCardinality', 'fix'),
('OpenGPTDialog', 'openGPTDialog'),
('Generate', 'generate');

INSERT INTO PolicyAllowsCategory (policyName, categoryName)
VALUES
('trial', 'add'),
('trial', 'fix'),
('trial', 'reification'),
('trial', 'explain'),
('trial', 'openGPTDialog'),
('trial', 'generate'),
('silver', 'add'),
('silver', 'fix'),
('silver', 'reification'),
('silver', 'explain'),
('silver', 'openGPTDialog'),
('silver', 'generate'),
('gold', 'add'),
('gold', 'fix'),
('gold', 'reification'),
('gold', 'explain'),
('gold', 'openGPTDialog'),
('gold', 'generate'),
('platinum', 'add'),
('platinum', 'fix'),
('platinum', 'reification'),
('platinum', 'explain'),
('platinum', 'openGPTDialog'),
('platinum', 'generate');

INSERT INTO Users (username, email, password, firstName, lastName, birthDate, status)
VALUES
('schemalink', 'admin@admin.com', '$2b$12$yZYH7Zgep3TO5uG3kQTiZepShn/7LDi6k/fq4K7Wp0VQ1PtqaMFOi', 'Admin', 'Admin', '2000-01-01', 'active');




CREATE OR REPLACE FUNCTION notify_user_status() RETURNS trigger AS $notify_user_status$
DECLARE
 to_email TEXT;
 user_name TEXT;
BEGIN
 IF OLD.status IS DISTINCT FROM NEW.status THEN
 to_email := NEW.email;
 user_name := NEW.username;
 PERFORM pg_notify('user_status', to_email || ',' || user_name || ',' || NEW.status::TEXT || ',' || OLD.status::TEXT);
 END IF;
 RETURN NEW;
END;
$notify_user_status$ LANGUAGE plpgsql;

CREATE TRIGGER send_status_email
AFTER UPDATE OF status ON Users
FOR EACH ROW
WHEN (OLD.status IS DISTINCT FROM NEW.status)
EXECUTE FUNCTION notify_user_status() ;





CREATE OR REPLACE FUNCTION notify_policy_status() RETURNS trigger AS $notify_policy_status$
DECLARE
 to_email TEXT;
 user_name TEXT;
BEGIN
 IF OLD.status IS DISTINCT FROM NEW.status THEN
 SELECT email INTO to_email FROM Users WHERE username = NEW.username;
 user_name := NEW.username;
 PERFORM pg_notify('policy_status', to_email || ',' || user_name || ',' || NEW.status::TEXT || ',' || OLD.status::TEXT);
 END IF;
 RETURN NEW;
END;
$notify_policy_status$ LANGUAGE plpgsql;

CREATE TRIGGER send_policy_status_email
AFTER UPDATE OF status ON UserSubscribesPolicy
FOR EACH ROW
WHEN (OLD.status IS DISTINCT FROM NEW.status)
EXECUTE FUNCTION notify_policy_status() ;

