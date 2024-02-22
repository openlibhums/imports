<?xml version="1.0" encoding="UTF-8"?>
<xsl:stylesheet version="1.0"
                xmlns:xsl="http://www.w3.org/1999/XSL/Transform"
                xmlns:xlink="http://www.w3.org/1999/xlink"
                exclude-result-prefixes="xlink">

    <xsl:output method="xml" encoding="utf-8" indent="yes" omit-xml-declaration="yes"/>


    <xsl:template match="article">
            <sec>
                <xsl:apply-templates/>
            </sec>
    </xsl:template>


    <xsl:template match="div">
        <sec>
            <xsl:if test="@id">
                    <xsl:attribute name="xml:id">
                        <xsl:value-of select="@id"/>
                    </xsl:attribute>
            </xsl:if>
            <xsl:apply-templates/>
        </sec>
    </xsl:template>

    <xsl:template match="h2 | h3 | h4 | h5 | h6">
        <heading>
            <xsl:apply-templates/>
        </heading>
    </xsl:template>

    <xsl:template match="p">
        <p>
            <xsl:if test="@id">
                <xsl:attribute name="xml:id">
                    <xsl:value-of select="@id"/>
                </xsl:attribute>
            </xsl:if>   
            <xsl:apply-templates/>
        </p>
    </xsl:template>
    
    <xsl:template match="hr">
        <hr />
    </xsl:template>


    <xsl:template match="span[@itemprop]">
        <named-content content-type="{ @itemprop }">
            <xsl:apply-templates/>
        </named-content>
    </xsl:template>

    <xsl:template match="a">
        <ext-link ext-link-type="uri" xlink:href="{@href}">
            <xsl:if test="@id">
                <xsl:attribute name="xml:id">
                    <xsl:value-of select="@id"/>
                </xsl:attribute>
            </xsl:if>   
            <xsl:apply-templates/>
        </ext-link>
    </xsl:template>

    <xsl:template match="i | em">
        <italic>
            <xsl:apply-templates/>
        </italic>
    </xsl:template>

    <xsl:template match="b | strong">
        <bold>
            <xsl:apply-templates/>
        </bold>
    </xsl:template>

    <xsl:template match="sub">
        <sub>
            <xsl:apply-templates/>
        </sub>
    </xsl:template>

    <xsl:template match="sup">
        <sup>
            <xsl:apply-templates/>
        </sup>
    </xsl:template>

    <xsl:template match="u">
        <underline>
            <xsl:apply-templates/>
        </underline>
    </xsl:template>

    <xsl:template match="br">
        <break/>
    </xsl:template>

    <xsl:template match="blockquote">
        <disp-quote>
            <xsl:apply-templates/>
        </disp-quote>
    </xsl:template>
      
    <xsl:template match="code">
        <code>
            <xsl:apply-templates/>
        </code>
    </xsl:template>
    
    <xsl:template match="img">
        <graphic>
            <xsl:attribute name="caption"><xsl:value-of select="@alt"/></xsl:attribute>
            <xsl:attribute name="xlink:href"><xsl:value-of select="@src"/></xsl:attribute>
        </graphic>
    </xsl:template>
    
    <!-- lists -->
    <xsl:template match="ul">
        <list>
            <xsl:attribute name="list-type">list-unord</xsl:attribute>
            <xsl:apply-templates/>
        </list>
    </xsl:template>
    
    <xsl:template match="ol">
        <list>
            <xsl:attribute name="list-type">order</xsl:attribute>
            <xsl:apply-templates/>
        </list>
    </xsl:template>
    
    <xsl:template match="li">
        <list-item>
            <xsl:apply-templates/>
        </list-item>
    </xsl:template>
    
    <!-- definition lists -->
    <xsl:template match="dl">
        <def-list>
            <xsl:apply-templates/>
        </def-list>
    </xsl:template>
    
    <xsl:template match="dt">
        <def-item>
            <xsl:apply-templates/>
        </def-item>
    </xsl:template>
    
    <xsl:template match="dd">
        <def>
            <xsl:apply-templates/>
        </def>
    </xsl:template>
    
    <!-- Tables -->
    <xsl:template match="table">
        <table-wrap xmlns="http://jats.nlm.nih.gov/ns/archiving/1.2/">
            <table>
                <thead>
                    <xsl:apply-templates select="thead"/>
                </thead>
                <tbody>
                    <xsl:apply-templates select="tbody"/>
                </tbody>
                <tfoot>
                    <xsl:apply-templates select="tfoot"/>
                </tfoot>
            </table>
        </table-wrap>
    </xsl:template>
    
    <xsl:template match="thead|tbody|trow">
        <xsl:apply-templates/>
    </xsl:template>
  
    <xsl:template match="tr">
        <tr>
          <xsl:apply-templates/>
        </tr>
    </xsl:template>
    
    <xsl:template match="td">
        <td>
            <xsl:apply-templates/>
        </td>
    </xsl:template>
    
    <xsl:template match="th">
        <th>
            <xsl:apply-templates/>
        </th>
    </xsl:template>
</xsl:stylesheet>
