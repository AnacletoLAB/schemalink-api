# Generated from pgs.g4 by ANTLR 4.13.2
from antlr4 import *
if "." in __name__:
    from .pgsParser import pgsParser
else:
    from pgsParser import pgsParser

# This class defines a complete listener for a parse tree produced by pgsParser.
class pgsListener(ParseTreeListener):

    # Enter a parse tree produced by pgsParser#pgs.
    def enterPgs(self, ctx:pgsParser.PgsContext):
        pass

    # Exit a parse tree produced by pgsParser#pgs.
    def exitPgs(self, ctx:pgsParser.PgsContext):
        pass


    # Enter a parse tree produced by pgsParser#createType.
    def enterCreateType(self, ctx:pgsParser.CreateTypeContext):
        pass

    # Exit a parse tree produced by pgsParser#createType.
    def exitCreateType(self, ctx:pgsParser.CreateTypeContext):
        pass


    # Enter a parse tree produced by pgsParser#createNodeType.
    def enterCreateNodeType(self, ctx:pgsParser.CreateNodeTypeContext):
        pass

    # Exit a parse tree produced by pgsParser#createNodeType.
    def exitCreateNodeType(self, ctx:pgsParser.CreateNodeTypeContext):
        pass


    # Enter a parse tree produced by pgsParser#createEdgeType.
    def enterCreateEdgeType(self, ctx:pgsParser.CreateEdgeTypeContext):
        pass

    # Exit a parse tree produced by pgsParser#createEdgeType.
    def exitCreateEdgeType(self, ctx:pgsParser.CreateEdgeTypeContext):
        pass


    # Enter a parse tree produced by pgsParser#createGraphType.
    def enterCreateGraphType(self, ctx:pgsParser.CreateGraphTypeContext):
        pass

    # Exit a parse tree produced by pgsParser#createGraphType.
    def exitCreateGraphType(self, ctx:pgsParser.CreateGraphTypeContext):
        pass


    # Enter a parse tree produced by pgsParser#graphType.
    def enterGraphType(self, ctx:pgsParser.GraphTypeContext):
        pass

    # Exit a parse tree produced by pgsParser#graphType.
    def exitGraphType(self, ctx:pgsParser.GraphTypeContext):
        pass


    # Enter a parse tree produced by pgsParser#typeForm.
    def enterTypeForm(self, ctx:pgsParser.TypeFormContext):
        pass

    # Exit a parse tree produced by pgsParser#typeForm.
    def exitTypeForm(self, ctx:pgsParser.TypeFormContext):
        pass


    # Enter a parse tree produced by pgsParser#graphTypeDefinition.
    def enterGraphTypeDefinition(self, ctx:pgsParser.GraphTypeDefinitionContext):
        pass

    # Exit a parse tree produced by pgsParser#graphTypeDefinition.
    def exitGraphTypeDefinition(self, ctx:pgsParser.GraphTypeDefinitionContext):
        pass


    # Enter a parse tree produced by pgsParser#elementTypes.
    def enterElementTypes(self, ctx:pgsParser.ElementTypesContext):
        pass

    # Exit a parse tree produced by pgsParser#elementTypes.
    def exitElementTypes(self, ctx:pgsParser.ElementTypesContext):
        pass


    # Enter a parse tree produced by pgsParser#elementType.
    def enterElementType(self, ctx:pgsParser.ElementTypeContext):
        pass

    # Exit a parse tree produced by pgsParser#elementType.
    def exitElementType(self, ctx:pgsParser.ElementTypeContext):
        pass


    # Enter a parse tree produced by pgsParser#nodeType.
    def enterNodeType(self, ctx:pgsParser.NodeTypeContext):
        pass

    # Exit a parse tree produced by pgsParser#nodeType.
    def exitNodeType(self, ctx:pgsParser.NodeTypeContext):
        pass


    # Enter a parse tree produced by pgsParser#edgeType.
    def enterEdgeType(self, ctx:pgsParser.EdgeTypeContext):
        pass

    # Exit a parse tree produced by pgsParser#edgeType.
    def exitEdgeType(self, ctx:pgsParser.EdgeTypeContext):
        pass


    # Enter a parse tree produced by pgsParser#middleType.
    def enterMiddleType(self, ctx:pgsParser.MiddleTypeContext):
        pass

    # Exit a parse tree produced by pgsParser#middleType.
    def exitMiddleType(self, ctx:pgsParser.MiddleTypeContext):
        pass


    # Enter a parse tree produced by pgsParser#endpointType.
    def enterEndpointType(self, ctx:pgsParser.EndpointTypeContext):
        pass

    # Exit a parse tree produced by pgsParser#endpointType.
    def exitEndpointType(self, ctx:pgsParser.EndpointTypeContext):
        pass


    # Enter a parse tree produced by pgsParser#labelPropertySpec.
    def enterLabelPropertySpec(self, ctx:pgsParser.LabelPropertySpecContext):
        pass

    # Exit a parse tree produced by pgsParser#labelPropertySpec.
    def exitLabelPropertySpec(self, ctx:pgsParser.LabelPropertySpecContext):
        pass


    # Enter a parse tree produced by pgsParser#labelSpec.
    def enterLabelSpec(self, ctx:pgsParser.LabelSpecContext):
        pass

    # Exit a parse tree produced by pgsParser#labelSpec.
    def exitLabelSpec(self, ctx:pgsParser.LabelSpecContext):
        pass


    # Enter a parse tree produced by pgsParser#propertySpec.
    def enterPropertySpec(self, ctx:pgsParser.PropertySpecContext):
        pass

    # Exit a parse tree produced by pgsParser#propertySpec.
    def exitPropertySpec(self, ctx:pgsParser.PropertySpecContext):
        pass


    # Enter a parse tree produced by pgsParser#properties.
    def enterProperties(self, ctx:pgsParser.PropertiesContext):
        pass

    # Exit a parse tree produced by pgsParser#properties.
    def exitProperties(self, ctx:pgsParser.PropertiesContext):
        pass


    # Enter a parse tree produced by pgsParser#property.
    def enterProperty(self, ctx:pgsParser.PropertyContext):
        pass

    # Exit a parse tree produced by pgsParser#property.
    def exitProperty(self, ctx:pgsParser.PropertyContext):
        pass


    # Enter a parse tree produced by pgsParser#propertyType.
    def enterPropertyType(self, ctx:pgsParser.PropertyTypeContext):
        pass

    # Exit a parse tree produced by pgsParser#propertyType.
    def exitPropertyType(self, ctx:pgsParser.PropertyTypeContext):
        pass


    # Enter a parse tree produced by pgsParser#key.
    def enterKey(self, ctx:pgsParser.KeyContext):
        pass

    # Exit a parse tree produced by pgsParser#key.
    def exitKey(self, ctx:pgsParser.KeyContext):
        pass


    # Enter a parse tree produced by pgsParser#labelName.
    def enterLabelName(self, ctx:pgsParser.LabelNameContext):
        pass

    # Exit a parse tree produced by pgsParser#labelName.
    def exitLabelName(self, ctx:pgsParser.LabelNameContext):
        pass


    # Enter a parse tree produced by pgsParser#typeName.
    def enterTypeName(self, ctx:pgsParser.TypeNameContext):
        pass

    # Exit a parse tree produced by pgsParser#typeName.
    def exitTypeName(self, ctx:pgsParser.TypeNameContext):
        pass


    # Enter a parse tree produced by pgsParser#dash.
    def enterDash(self, ctx:pgsParser.DashContext):
        pass

    # Exit a parse tree produced by pgsParser#dash.
    def exitDash(self, ctx:pgsParser.DashContext):
        pass


    # Enter a parse tree produced by pgsParser#rightArrowHead.
    def enterRightArrowHead(self, ctx:pgsParser.RightArrowHeadContext):
        pass

    # Exit a parse tree produced by pgsParser#rightArrowHead.
    def exitRightArrowHead(self, ctx:pgsParser.RightArrowHeadContext):
        pass



del pgsParser