--
-- PostgreSQL database dump
--

-- Dumped from database version 16.3
-- Dumped by pg_dump version 16.3

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: notify_policy_status(); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.notify_policy_status() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
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
$$;


ALTER FUNCTION public.notify_policy_status() OWNER TO postgres;

--
-- Name: notify_user_status(); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.notify_user_status() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
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
$$;


ALTER FUNCTION public.notify_user_status() OWNER TO postgres;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: category; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.category (
    name character varying(13) NOT NULL,
    CONSTRAINT category_name_check CHECK (((name)::text = ANY ((ARRAY['add'::character varying, 'fix'::character varying, 'reification'::character varying, 'explain'::character varying, 'openGPTDialog'::character varying, 'generate'::character varying])::text[])))
);


ALTER TABLE public.category OWNER TO postgres;

--
-- Name: operation; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.operation (
    name character varying(50) NOT NULL,
    target character varying(8),
    description character varying(100) NOT NULL,
    CONSTRAINT operation_target_check CHECK (((target)::text = ANY ((ARRAY['class'::character varying, 'relation'::character varying, 'subgraph'::character varying])::text[])))
);


ALTER TABLE public.operation OWNER TO postgres;

--
-- Name: operationiscategory; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.operationiscategory (
    operationname character varying(50) NOT NULL,
    categoryname character varying(13) NOT NULL,
    CONSTRAINT operationiscategory_categoryname_check CHECK (((categoryname)::text = ANY ((ARRAY['add'::character varying, 'fix'::character varying, 'reification'::character varying, 'explain'::character varying, 'openGPTDialog'::character varying, 'generate'::character varying])::text[])))
);


ALTER TABLE public.operationiscategory OWNER TO postgres;

--
-- Name: policy; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.policy (
    name character varying(8) NOT NULL,
    maxaccess integer,
    threshold integer,
    CONSTRAINT policy_name_check CHECK (((name)::text = ANY ((ARRAY['trial'::character varying, 'silver'::character varying, 'gold'::character varying, 'platinum'::character varying])::text[])))
);


ALTER TABLE public.policy OWNER TO postgres;

--
-- Name: policyallowscategory; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.policyallowscategory (
    policyname character varying(8) NOT NULL,
    categoryname character varying(13) NOT NULL,
    CONSTRAINT policyallowscategory_categoryname_check CHECK (((categoryname)::text = ANY ((ARRAY['add'::character varying, 'fix'::character varying, 'reification'::character varying, 'explain'::character varying, 'openGPTDialog'::character varying, 'generate'::character varying])::text[]))),
    CONSTRAINT policyallowscategory_policyname_check CHECK (((policyname)::text = ANY ((ARRAY['trial'::character varying, 'silver'::character varying, 'gold'::character varying, 'platinum'::character varying])::text[])))
);


ALTER TABLE public.policyallowscategory OWNER TO postgres;

--
-- Name: usermadeoperation; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.usermadeoperation (
    username character varying(50) NOT NULL,
    date timestamp with time zone NOT NULL,
    operationname character varying(50) NOT NULL
);


ALTER TABLE public.usermadeoperation OWNER TO postgres;

--
-- Name: users; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.users (
    username character varying(50) NOT NULL,
    email character varying(255) NOT NULL,
    password character varying(255) NOT NULL,
    firstname character varying(20) NOT NULL,
    lastname character varying(20) NOT NULL,
    birthdate date NOT NULL,
    status character varying(8) NOT NULL,
    CONSTRAINT users_status_check CHECK (((status)::text = ANY ((ARRAY['pending'::character varying, 'active'::character varying, 'disabled'::character varying, 'blocked'::character varying])::text[])))
);


ALTER TABLE public.users OWNER TO postgres;

--
-- Name: usersubscribespolicy; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.usersubscribespolicy (
    username character varying(50) NOT NULL,
    startdate timestamp with time zone,
    enddate timestamp with time zone,
    requestdate timestamp with time zone NOT NULL,
    status character varying(8) NOT NULL,
    numoperations integer,
    policyname character varying(8) NOT NULL,
    CONSTRAINT usersubscribespolicy_policyname_check CHECK (((policyname)::text = ANY ((ARRAY['trial'::character varying, 'silver'::character varying, 'gold'::character varying, 'platinum'::character varying])::text[]))),
    CONSTRAINT usersubscribespolicy_status_check CHECK (((status)::text = ANY ((ARRAY['pending'::character varying, 'active'::character varying, 'rejected'::character varying, 'expired'::character varying])::text[])))
);


ALTER TABLE public.usersubscribespolicy OWNER TO postgres;

--
-- Data for Name: category; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.category (name) FROM stdin;
add
fix
reification
explain
openGPTDialog
generate
\.


--
-- Data for Name: operation; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.operation (name, target, description) FROM stdin;
AddClassSimilarToClass	class	add a new class semantically similar to another class
AddClassAssociatedToClass	class	add a new class in relation with another class
AddAttributeToRelationship	relation	add relevant attributes to a relationship
AddClassesSimilarToEntities	subgraph	add one or more new classes that semantically fit the context\ndefined by subgraph
ReifyClass	class	create a class for representing the instance of a class
ExplainClass	class	explain in human-friendly terms the role of class in the schema
ExplainEntities	subgraph	explain in human-friendly terms the role of a portion of the schema in the\nschema
FixClassName	class	rename a class
FixClassOntology	class	enhance the relevant ontologies for a class
FixRelationshipCardinality	relation	fix cardinality for a relationship
OpenGPTDialog	\N	openGPTDialog
Generate	\N	generate
AddAttributesToClass	class	add relevant attributes to a class
AddAttributesDescription	class	add relevant descriptions to the attributes of the class
AddParentClass	class	enhance the parent class for the class
AddChildClass	class	introduce one or more child classes for the class
AnnotateClassOntology	class	introduce one or more ontologies that are suitable for describing the class
AnnotateClassExample	class	add example instances to the class
AnnotateClassDescription	class	add a detailed description to the class
FixClassDescription	class	update/improve the description belonging to the class
FixClassAttributesName	class	update the attributes name belonging to the class
FixClassAttributesDescription	class	update the description of the attributes belonging to the class
FixClassAttributesType	class	review the attributes within the class and update their types
FixClassExample	class	update/improve the examples belonging to the class
AddRelationshipAttributesDescription	relation	add relevant descriptions to the attributes of the association
AnnotateRelationshipOntology	relation	introduce one or more ontologies that are suitable for describing the association
AnnotateRelationshipExample	relation	add example instances to the association
AnnotateRelationshipDescription	relation	add a detailed description to the association
FixRelationshipName	relation	update the association by renaming it to better reflect its role and context within the schema
FixRelationshipDescription	relation	update/improve the description belonging to the association
FixRelationshipAttributesName	relation	update the attributes belonging to the association by renaming them better
FixRelationshipAttributesType	relation	update relation attributes types to better reflect their intended semantics
FixRelationshipOntology	relation	propose relevant ontologies that could be used to annotate the association
FixRelationshipExample	relation	update/improve the examples belonging to the association
ExplainRelationship	relation	explain in human-friendly terms the association
AddAssociationsSimilarToEntities	subgraph	add one or more new associations that semantically fit the context defined by the subgraph
AnnotateSubschemaOntology	subgraph	propose relevant ontologies that could be used to annotate associations and classes of the subgraph
AnnotateSubschemaExample	subgraph	add example instances to the associations and the classes belonging to the subgraph
AnnotateSubschemaDescription	subgraph	add a description to the associations and the classes belonging to the subgraph
FixClassesAndAssociationsName	subgraph	update the names of the associations and classes belonging to the subgraph
FixClassesAndAssociationsDescription	subgraph	add/update the description of the associations and classes belonging to the subgraph
FixSubschemaOntology	subgraph	add/update an ontology suitable for annotating associations and classes belonging to the subgraph
FixSubschemaExample	subgraph	update/improve the examples for the associations and classes belonging to the subgraph
FixSubschemaCardinalities	subgraph	update/improve the cardinality for the associations belonging to the subgraph
\.


--
-- Data for Name: operationiscategory; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.operationiscategory (operationname, categoryname) FROM stdin;
AddClassSimilarToClass	add
AddClassAssociatedToClass	add
AddAttributeToRelationship	add
AddClassesSimilarToEntities	add
ReifyClass	reification
ExplainClass	explain
ExplainEntities	explain
FixClassName	fix
FixClassOntology	fix
FixRelationshipCardinality	fix
OpenGPTDialog	openGPTDialog
Generate	generate
\.


--
-- Data for Name: policy; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.policy (name, maxaccess, threshold) FROM stdin;
trial	10	3
silver	50	10
gold	100	15
platinum	\N	\N
\.


--
-- Data for Name: policyallowscategory; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.policyallowscategory (policyname, categoryname) FROM stdin;
trial	add
trial	fix
trial	reification
trial	explain
trial	openGPTDialog
trial	generate
silver	add
silver	fix
silver	reification
silver	explain
silver	openGPTDialog
silver	generate
gold	add
gold	fix
gold	reification
gold	explain
gold	openGPTDialog
gold	generate
platinum	add
platinum	fix
platinum	reification
platinum	explain
platinum	openGPTDialog
platinum	generate
\.


--
-- Data for Name: users; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.users (username, email, password, firstname, lastname, birthdate, status) FROM stdin;
schemalink	admin@admin.com	$2b$12$yZYH7Zgep3TO5uG3kQTiZepShn/7LDi6k/fq4K7Wp0VQ1PtqaMFOi	Admin	Admin	2000-01-01	active
\.


--
-- Data for Name: usersubscribespolicy; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.usersubscribespolicy (username, startdate, enddate, requestdate, status, numoperations, policyname) FROM stdin;
\.


--
-- Name: category category_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.category
    ADD CONSTRAINT category_pkey PRIMARY KEY (name);


--
-- Name: operation operation_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.operation
    ADD CONSTRAINT operation_pkey PRIMARY KEY (name);


--
-- Name: operationiscategory operationiscategory_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.operationiscategory
    ADD CONSTRAINT operationiscategory_pkey PRIMARY KEY (operationname, categoryname);


--
-- Name: policy policy_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.policy
    ADD CONSTRAINT policy_pkey PRIMARY KEY (name);


--
-- Name: policyallowscategory policyallowscategory_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.policyallowscategory
    ADD CONSTRAINT policyallowscategory_pkey PRIMARY KEY (policyname, categoryname);


--
-- Name: usermadeoperation usermadeoperation_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.usermadeoperation
    ADD CONSTRAINT usermadeoperation_pkey PRIMARY KEY (username, date);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (username);


--
-- Name: usersubscribespolicy usersubscribespolicy_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.usersubscribespolicy
    ADD CONSTRAINT usersubscribespolicy_pkey PRIMARY KEY (username, requestdate);


--
-- Name: usersubscribespolicy send_policy_status_email; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER send_policy_status_email AFTER UPDATE OF status ON public.usersubscribespolicy FOR EACH ROW WHEN (((old.status)::text IS DISTINCT FROM (new.status)::text)) EXECUTE FUNCTION public.notify_policy_status();


--
-- Name: users send_status_email; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER send_status_email AFTER UPDATE OF status ON public.users FOR EACH ROW WHEN (((old.status)::text IS DISTINCT FROM (new.status)::text)) EXECUTE FUNCTION public.notify_user_status();


--
-- Name: operationiscategory operationiscategory_categoryname_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.operationiscategory
    ADD CONSTRAINT operationiscategory_categoryname_fkey FOREIGN KEY (categoryname) REFERENCES public.category(name) ON DELETE RESTRICT;


--
-- Name: operationiscategory operationiscategory_operationname_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.operationiscategory
    ADD CONSTRAINT operationiscategory_operationname_fkey FOREIGN KEY (operationname) REFERENCES public.operation(name) ON DELETE CASCADE;


--
-- Name: policyallowscategory policyallowscategory_categoryname_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.policyallowscategory
    ADD CONSTRAINT policyallowscategory_categoryname_fkey FOREIGN KEY (categoryname) REFERENCES public.category(name) ON DELETE RESTRICT;


--
-- Name: policyallowscategory policyallowscategory_policyname_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.policyallowscategory
    ADD CONSTRAINT policyallowscategory_policyname_fkey FOREIGN KEY (policyname) REFERENCES public.policy(name) ON DELETE CASCADE;


--
-- Name: usermadeoperation usermadeoperation_operationname_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.usermadeoperation
    ADD CONSTRAINT usermadeoperation_operationname_fkey FOREIGN KEY (operationname) REFERENCES public.operation(name) ON DELETE RESTRICT;


--
-- Name: usermadeoperation usermadeoperation_username_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.usermadeoperation
    ADD CONSTRAINT usermadeoperation_username_fkey FOREIGN KEY (username) REFERENCES public.users(username) ON DELETE CASCADE;


--
-- Name: usersubscribespolicy usersubscribespolicy_policyname_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.usersubscribespolicy
    ADD CONSTRAINT usersubscribespolicy_policyname_fkey FOREIGN KEY (policyname) REFERENCES public.policy(name) ON DELETE RESTRICT;


--
-- Name: usersubscribespolicy usersubscribespolicy_username_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.usersubscribespolicy
    ADD CONSTRAINT usersubscribespolicy_username_fkey FOREIGN KEY (username) REFERENCES public.users(username) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--

