from __future__ import annotations 

import re
import sys
from datetime import (
    date,
    datetime,
    time
)
from decimal import Decimal 
from enum import Enum 
from typing import (
    Any,
    ClassVar,
    Literal,
    Optional,
    Union
)

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    RootModel,
    field_validator
)


metamodel_version = "None"
version = "None"


class ConfiguredBaseModel(BaseModel):
    model_config = ConfigDict(
        validate_assignment = True,
        validate_default = True,
        extra = "forbid",
        arbitrary_types_allowed = True,
        use_enum_values = True,
        strict = False,
    )
    pass




class LinkMLMeta(RootModel):
    root: dict[str, Any] = {}
    model_config = ConfigDict(frozen=True)

    def __getattr__(self, key:str):
        return getattr(self.root, key)

    def __getitem__(self, key:str):
        return self.root[key]

    def __setitem__(self, key:str, value):
        self.root[key] = value

    def __contains__(self, key:str) -> bool:
        return key in self.root


linkml_meta = LinkMLMeta({'default_prefix': 'https://schemalink.biodata.di.unimi.it/archaeological_excavation_schema/',
     'default_range': 'string',
     'description': '',
     'id': 'https://schemalink.biodata.di.unimi.it/archaeological_excavation_schema',
     'imports': ['linkml:types'],
     'license': 'https://creativecommons.org/publicdomain/zero/1.0/',
     'name': 'archaeological_excavation_schema',
     'prefixes': {'ADO': {'prefix_prefix': 'ADO',
                          'prefix_reference': 'http://purl.obolibrary.org/obo/ado.owl'},
                  'BFO': {'prefix_prefix': 'BFO',
                          'prefix_reference': 'http://purl.obolibrary.org/obo/bfo.owl'},
                  'SO': {'prefix_prefix': 'SO',
                         'prefix_reference': 'http://purl.obolibrary.org/obo/so.owl'},
                  'linkml': {'prefix_prefix': 'linkml',
                             'prefix_reference': 'https://w3id.org/linkml/'},
                  'rdf': {'prefix_prefix': 'rdf',
                          'prefix_reference': 'https://www.w3.org/1999/02/22-rdf-syntax-ns#'},
                  'rdfs': {'prefix_prefix': 'rdfs',
                           'prefix_reference': 'http://www.w3.org/2000/01/rdf-schema#'}},
     'title': 'Archaeological Excavation Schema'} )


class Node(ConfiguredBaseModel):
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'abstract': True,
         'from_schema': 'https://schemalink.biodata.di.unimi.it/archaeological_excavation_schema'})

    id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'alias': 'id', 'domain_of': ['Node']} })
    name: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'alias': 'name', 'domain_of': ['Node'], 'slot_uri': 'rdfs:label'} })
    category: Literal["Node"] = Field(default="Node", json_schema_extra = { "linkml_meta": {'alias': 'category',
         'designates_type': True,
         'domain_of': ['Node'],
         'slot_uri': 'rdf:type'} })
    types: Optional[list[str]] = Field(default=None, json_schema_extra = { "linkml_meta": {'alias': 'types', 'domain_of': ['Node']} })


class Edge(ConfiguredBaseModel):
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'abstract': True,
         'class_uri': 'rdf:Statement',
         'from_schema': 'https://schemalink.biodata.di.unimi.it/archaeological_excavation_schema'})

    subject: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'alias': 'subject', 'domain_of': ['Edge'], 'slot_uri': 'rdf:subject'} })
    predicate: Literal["https://schemalink.biodata.di.unimi.it/archaeological_excavation_schema/Edge","https://www.w3.org/1999/02/22-rdf-syntax-ns#Statement","rdf:Statement"] = Field(default="rdf:Statement", json_schema_extra = { "linkml_meta": {'alias': 'predicate',
         'designates_type': True,
         'domain_of': ['Edge'],
         'slot_uri': 'rdf:predicate'} })
    object: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'alias': 'object', 'domain_of': ['Edge'], 'slot_uri': 'rdf:object'} })
    type: Literal["https://schemalink.biodata.di.unimi.it/archaeological_excavation_schema/Edge","https://www.w3.org/1999/02/22-rdf-syntax-ns#Statement","rdf:Statement"] = Field(default="rdf:Statement", json_schema_extra = { "linkml_meta": {'alias': 'type',
         'designates_type': True,
         'domain_of': ['Edge'],
         'slot_uri': 'rdf:type'} })


class Graphs(ConfiguredBaseModel):
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://schemalink.biodata.di.unimi.it/archaeological_excavation_schema'})

    nodes: Optional[list[Union[Node,Archaeologicalexcavation,Archaeologicalassessment]]] = Field(default=None, json_schema_extra = { "linkml_meta": {'alias': 'nodes', 'domain_of': ['Graphs']} })
    edges: Optional[list[Union[Edge,ArchaeologicalexcavationExcavationAssessesArchaeologicalassessmentEdge,ArchaeologicalexcavationExcavationAssessesArchaeologicalassessmentRelationship]]] = Field(default=None, json_schema_extra = { "linkml_meta": {'alias': 'edges', 'domain_of': ['Graphs']} })


class ArchaeologicalexcavationExcavationAssessesArchaeologicalassessmentEdge(Edge):
    """
    A relationship of type \"excavation assesses\" from Archaeologicalexcavation to Archaeologicalassessment.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'annotations': {'annotators': {'tag': 'annotators', 'value': 'sqlite:obo:so'}},
         'from_schema': 'https://schemalink.biodata.di.unimi.it/archaeological_excavation_schema',
         'slot_usage': {'predicate': {'equals_string': 'excavation assesses',
                                      'name': 'predicate'}}})

    attribute_numer_one: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'alias': 'attribute_numer_one',
         'domain_of': ['ArchaeologicalexcavationExcavationAssessesArchaeologicalassessmentEdge']} })
    attribute_number_two: Optional[list[date]] = Field(default=None, description="""sadgbd""", json_schema_extra = { "linkml_meta": {'alias': 'attribute_number_two',
         'domain_of': ['ArchaeologicalexcavationExcavationAssessesArchaeologicalassessmentEdge']} })
    attibute_three: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'alias': 'attibute_three',
         'domain_of': ['ArchaeologicalexcavationExcavationAssessesArchaeologicalassessmentEdge']} })
    subject: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'alias': 'subject', 'domain_of': ['Edge'], 'slot_uri': 'rdf:subject'} })
    predicate: Literal["https://schemalink.biodata.di.unimi.it/archaeological_excavation_schema/ArchaeologicalexcavationExcavationAssessesArchaeologicalassessmentEdge"] = Field(default="https://schemalink.biodata.di.unimi.it/archaeological_excavation_schema/ArchaeologicalexcavationExcavationAssessesArchaeologicalassessmentEdge", json_schema_extra = { "linkml_meta": {'alias': 'predicate',
         'designates_type': True,
         'domain_of': ['Edge'],
         'equals_string': 'excavation assesses',
         'slot_uri': 'rdf:predicate'} })
    object: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'alias': 'object', 'domain_of': ['Edge'], 'slot_uri': 'rdf:object'} })
    type: Literal["https://schemalink.biodata.di.unimi.it/archaeological_excavation_schema/ArchaeologicalexcavationExcavationAssessesArchaeologicalassessmentEdge"] = Field(default="https://schemalink.biodata.di.unimi.it/archaeological_excavation_schema/ArchaeologicalexcavationExcavationAssessesArchaeologicalassessmentEdge", json_schema_extra = { "linkml_meta": {'alias': 'type',
         'designates_type': True,
         'domain_of': ['Edge'],
         'slot_uri': 'rdf:type'} })


class ArchaeologicalexcavationExcavationAssessesArchaeologicalassessmentRelationship(ArchaeologicalexcavationExcavationAssessesArchaeologicalassessmentEdge):
    """
    A relationship where the subject is a Archaeologicalexcavation and where the object is a Archaeologicalassessment. A triple where the subject is a Excavation and where the object is a Assessment.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'annotations': {'prompt.examples': {'tag': 'prompt.examples',
                                             'value': 'test1, test2'}},
         'from_schema': 'https://schemalink.biodata.di.unimi.it/archaeological_excavation_schema',
         'slot_usage': {'object': {'annotations': {'prompt.examples': {'tag': 'prompt.examples',
                                                                       'value': ''}},
                                   'maximum_cardinality': 2,
                                   'minimum_cardinality': 0,
                                   'name': 'object',
                                   'range': 'Archaeologicalassessment'},
                        'subject': {'annotations': {'prompt.examples': {'tag': 'prompt.examples',
                                                                        'value': ''}},
                                    'maximum_cardinality': 2,
                                    'minimum_cardinality': 1,
                                    'name': 'subject',
                                    'range': 'Archaeologicalexcavation'}}})

    attribute_numer_one: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'alias': 'attribute_numer_one',
         'domain_of': ['ArchaeologicalexcavationExcavationAssessesArchaeologicalassessmentEdge']} })
    attribute_number_two: Optional[list[date]] = Field(default=None, description="""sadgbd""", json_schema_extra = { "linkml_meta": {'alias': 'attribute_number_two',
         'domain_of': ['ArchaeologicalexcavationExcavationAssessesArchaeologicalassessmentEdge']} })
    attibute_three: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'alias': 'attibute_three',
         'domain_of': ['ArchaeologicalexcavationExcavationAssessesArchaeologicalassessmentEdge']} })
    subject: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'alias': 'subject',
         'annotations': {'prompt.examples': {'tag': 'prompt.examples', 'value': ''}},
         'domain_of': ['Edge'],
         'slot_uri': 'rdf:subject'} })
    predicate: Literal["https://schemalink.biodata.di.unimi.it/archaeological_excavation_schema/ArchaeologicalexcavationExcavationAssessesArchaeologicalassessmentRelationship"] = Field(default="https://schemalink.biodata.di.unimi.it/archaeological_excavation_schema/ArchaeologicalexcavationExcavationAssessesArchaeologicalassessmentRelationship", json_schema_extra = { "linkml_meta": {'alias': 'predicate',
         'designates_type': True,
         'domain_of': ['Edge'],
         'equals_string': 'excavation assesses',
         'slot_uri': 'rdf:predicate'} })
    object: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'alias': 'object',
         'annotations': {'prompt.examples': {'tag': 'prompt.examples', 'value': ''}},
         'domain_of': ['Edge'],
         'slot_uri': 'rdf:object'} })
    type: Literal["https://schemalink.biodata.di.unimi.it/archaeological_excavation_schema/ArchaeologicalexcavationExcavationAssessesArchaeologicalassessmentRelationship"] = Field(default="https://schemalink.biodata.di.unimi.it/archaeological_excavation_schema/ArchaeologicalexcavationExcavationAssessesArchaeologicalassessmentRelationship", json_schema_extra = { "linkml_meta": {'alias': 'type',
         'designates_type': True,
         'domain_of': ['Edge'],
         'slot_uri': 'rdf:type'} })


class Archaeologicalexcavation(Node):
    """
    Represents an archaeological excavation event.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'annotations': {'annotators': {'tag': 'annotators',
                                        'value': 'sqlite:obo:ado'}},
         'from_schema': 'https://schemalink.biodata.di.unimi.it/archaeological_excavation_schema',
         'id_prefixes': ['ADO']})

    excavation_id: str = Field(default=..., description="""Unique identifier for the excavation.""", json_schema_extra = { "linkml_meta": {'alias': 'excavation_id', 'domain_of': ['Archaeologicalexcavation']} })
    location: Optional[str] = Field(default=None, description="""The city where the excavation took place.""", json_schema_extra = { "linkml_meta": {'alias': 'location',
         'domain_of': ['Archaeologicalexcavation', 'Archaeologicalassessment']} })
    date: Optional[date] = Field(default=None, description="""The date when the excavation occurred.""", json_schema_extra = { "linkml_meta": {'alias': 'date',
         'domain_of': ['Archaeologicalexcavation', 'Archaeologicalassessment']} })
    description: Optional[str] = Field(default=None, description="""A detailed description of the excavation.""", json_schema_extra = { "linkml_meta": {'alias': 'description',
         'domain_of': ['Archaeologicalexcavation', 'Archaeologicalassessment']} })
    findings: Optional[list[str]] = Field(default=None, description="""List of findings from the excavation.""", json_schema_extra = { "linkml_meta": {'alias': 'findings',
         'domain_of': ['Archaeologicalexcavation', 'Archaeologicalassessment']} })
    id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'alias': 'id', 'domain_of': ['Node']} })
    name: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'alias': 'name', 'domain_of': ['Node'], 'slot_uri': 'rdfs:label'} })
    category: Literal["Archaeologicalexcavation"] = Field(default="Archaeologicalexcavation", json_schema_extra = { "linkml_meta": {'alias': 'category',
         'designates_type': True,
         'domain_of': ['Node'],
         'slot_uri': 'rdf:type'} })
    types: Optional[list[str]] = Field(default=None, json_schema_extra = { "linkml_meta": {'alias': 'types', 'domain_of': ['Node']} })


class Archaeologicalassessment(Node):
    """
    Represents an archaeological survey event, typically conducted to assess the potential for excavation.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://schemalink.biodata.di.unimi.it/archaeological_excavation_schema'})

    survey_id: str = Field(default=..., description="""Unique identifier for the survey.""", json_schema_extra = { "linkml_meta": {'alias': 'survey_id', 'domain_of': ['Archaeologicalassessment']} })
    location: Optional[str] = Field(default=None, description="""The area where the survey was conducted.""", json_schema_extra = { "linkml_meta": {'alias': 'location',
         'domain_of': ['Archaeologicalexcavation', 'Archaeologicalassessment']} })
    date: Optional[date] = Field(default=None, description="""The date when the survey occurred.""", json_schema_extra = { "linkml_meta": {'alias': 'date',
         'domain_of': ['Archaeologicalexcavation', 'Archaeologicalassessment']} })
    description: Optional[str] = Field(default=None, description="""A detailed description of the survey.""", json_schema_extra = { "linkml_meta": {'alias': 'description',
         'domain_of': ['Archaeologicalexcavation', 'Archaeologicalassessment']} })
    findings: Optional[list[str]] = Field(default=None, description="""List of findings from the survey.""", json_schema_extra = { "linkml_meta": {'alias': 'findings',
         'domain_of': ['Archaeologicalexcavation', 'Archaeologicalassessment']} })
    id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'alias': 'id', 'domain_of': ['Node']} })
    name: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'alias': 'name', 'domain_of': ['Node'], 'slot_uri': 'rdfs:label'} })
    category: Literal["Archaeologicalassessment"] = Field(default="Archaeologicalassessment", json_schema_extra = { "linkml_meta": {'alias': 'category',
         'designates_type': True,
         'domain_of': ['Node'],
         'slot_uri': 'rdf:type'} })
    types: Optional[list[str]] = Field(default=None, json_schema_extra = { "linkml_meta": {'alias': 'types', 'domain_of': ['Node']} })


# Model rebuild
# see https://pydantic-docs.helpmanual.io/usage/models/#rebuilding-a-model
Node.model_rebuild()
Edge.model_rebuild()
Graphs.model_rebuild()
ArchaeologicalexcavationExcavationAssessesArchaeologicalassessmentEdge.model_rebuild()
ArchaeologicalexcavationExcavationAssessesArchaeologicalassessmentRelationship.model_rebuild()
Archaeologicalexcavation.model_rebuild()
Archaeologicalassessment.model_rebuild()
