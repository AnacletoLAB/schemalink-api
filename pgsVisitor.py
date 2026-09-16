# Generated from pgs.g4 by ANTLR 4.13.2
from antlr4 import *
if "." in __name__:
    from .pgsParser import pgsParser
else:
    from pgsParser import pgsParser

# This class defines a complete generic visitor for a parse tree produced by pgsParser.

class pgsVisitor(ParseTreeVisitor):

    # Visit a parse tree produced by pgsParser#pgs.
    def visitPgs(self, ctx:pgsParser.PgsContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by pgsParser#createType.
    def visitCreateType(self, ctx:pgsParser.CreateTypeContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by pgsParser#createNodeType.
    def visitCreateNodeType(self, ctx:pgsParser.CreateNodeTypeContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by pgsParser#createEdgeType.
    def visitCreateEdgeType(self, ctx:pgsParser.CreateEdgeTypeContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by pgsParser#createGraphType.
    def visitCreateGraphType(self, ctx:pgsParser.CreateGraphTypeContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by pgsParser#graphType.
    def visitGraphType(self, ctx:pgsParser.GraphTypeContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by pgsParser#typeForm.
    def visitTypeForm(self, ctx:pgsParser.TypeFormContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by pgsParser#graphTypeDefinition.
    def visitGraphTypeDefinition(self, ctx:pgsParser.GraphTypeDefinitionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by pgsParser#elementTypes.
    def visitElementTypes(self, ctx:pgsParser.ElementTypesContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by pgsParser#elementType.
    def visitElementType(self, ctx:pgsParser.ElementTypeContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by pgsParser#nodeType.
    def visitNodeType(self, ctx:pgsParser.NodeTypeContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by pgsParser#edgeType.
    def visitEdgeType(self, ctx:pgsParser.EdgeTypeContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by pgsParser#middleType.
    def visitMiddleType(self, ctx:pgsParser.MiddleTypeContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by pgsParser#endpointType.
    def visitEndpointType(self, ctx:pgsParser.EndpointTypeContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by pgsParser#labelPropertySpec.
    def visitLabelPropertySpec(self, ctx:pgsParser.LabelPropertySpecContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by pgsParser#labelSpec.
    def visitLabelSpec(self, ctx:pgsParser.LabelSpecContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by pgsParser#propertySpec.
    def visitPropertySpec(self, ctx:pgsParser.PropertySpecContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by pgsParser#properties.
    def visitProperties(self, ctx:pgsParser.PropertiesContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by pgsParser#property.
    def visitProperty(self, ctx:pgsParser.PropertyContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by pgsParser#propertyType.
    def visitPropertyType(self, ctx:pgsParser.PropertyTypeContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by pgsParser#key.
    def visitKey(self, ctx:pgsParser.KeyContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by pgsParser#labelName.
    def visitLabelName(self, ctx:pgsParser.LabelNameContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by pgsParser#typeName.
    def visitTypeName(self, ctx:pgsParser.TypeNameContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by pgsParser#dash.
    def visitDash(self, ctx:pgsParser.DashContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by pgsParser#rightArrowHead.
    def visitRightArrowHead(self, ctx:pgsParser.RightArrowHeadContext):
        return self.visitChildren(ctx)



del pgsParser