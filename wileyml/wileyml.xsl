<?xml version="1.0" encoding="UTF-8"?>

<xsl:stylesheet
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xmlns:xlink="http://www.w3.org/1999/xlink"
    xmlns:xsl="http://www.w3.org/1999/XSL/Transform"
    xmlns:mml="http://www.w3.org/1998/Math/MathML"
    xmlns:wiley="http://www.wiley.com/namespaces/wiley/wiley"
    xmlns:wml="http://www.wiley.com/namespaces/wiley"
    xmlns:utils="https://example.org"
    exclude-result-prefixes="xsi wiley wml utils"
    version="2.0">
    
    <xsl:output
        method="xml" 
        indent="yes"
        doctype-public="-//NLM//DTD JATS (Z39.96) Journal Publishing DTD v1.2 20120330//EN" 
        doctype-system="http://jats.nlm.nih.gov/publishing/1.2/JATS-journalpublishing1.dtd"
    />
    <xsl:strip-space elements="*"/>
    
    <xsl:variable name="jats-date-parts">
        <part idx="1">day</part>
        <part idx="2">month</part>
        <part idx="3">year</part>
    </xsl:variable>

    <xsl:template match="/">
        <article article-type="research-article" dtd-version="1.2" xml:lang="en">
          <xsl:apply-templates />
      </article>
    </xsl:template>
    
    <!-- Start JATS  front -->
    <xsl:template match="wml:header">
        <!-- Here starts the builder of the JATS front, the order of each applied template is determined by the JATS spec. All templates are defined below -->
        <front>
            <journal-meta>
                <xsl:apply-templates select="wml:publicationMeta[@level='product']"/>
            </journal-meta>
            <article-meta>
                <xsl:apply-templates select="wml:publicationMeta[@level='unit']/wml:doi"/>
                <xsl:call-template name="article-title-block" />
                <xsl:apply-templates select="wml:contentMeta/wml:creators"/>
                <xsl:apply-templates select="wml:contentMeta/wml:affiliationGroup"/>
                <xsl:apply-templates select="wml:publicationMeta[@level='unit']/wml:eventGroup/wml:event"/>
                <xsl:call-template name="issue-meta-block" />
                <xsl:call-template name="page-numbers-block" />
                <xsl:call-template name="permissions-block"/>
                <xsl:apply-templates select="wml:contentMeta/wml:abstractGroup"/>
                <xsl:apply-templates select="wml:contentMeta/wml:keywordGroup"/>
                <xsl:apply-templates select="wml:contentMeta/wml:countGroup"/>
            </article-meta>
        </front>
    </xsl:template>
    
    <xsl:template match="wml:publicationMeta[@level='product']">
        <xsl:apply-templates select="wml:idGroup"/>
        <xsl:apply-templates select="wml:titleGroup"/>
        <xsl:apply-templates select="wml:issn"/>        
    </xsl:template>
    
    <xsl:template match="wml:idGroup/wml:id[@type='product']">
        <journal-id>
            <xsl:value-of select="@value" />
        </journal-id>
    </xsl:template>
    
    <xsl:template match="wml:publicationMeta[@level='product']/wml:titleGroup">
        <journal-title-group>
            <journal-title>
                <xsl:value-of select="./wml:title[@type='main']/text()" />
            </journal-title>
            <abbrev-journal-title>
                <xsl:value-of select="./wml:title[@type='short']/text()" />
            </abbrev-journal-title>
        </journal-title-group>
    </xsl:template>

    <xsl:template match="wml:publicationMeta[@level='unit'] | wml:publicationMeta[@level='part'] | contentMeta">
        <xsl:apply-templates select="wml:idGroup"/>
        <title-group>
            <article-title><xsl:apply-templates select="wml:titleGroup" /></article-title>
        </title-group>
    </xsl:template>
    
    <xsl:template match="wml:publicationMeta[@level='unit']/wml:doi">
        <article-id pub-id-type="doi"><xsl:value-of select="."/></article-id>
    </xsl:template>
    
    <xsl:template name="article-title-block">
            <title-group>
                <article-title>
                    <xsl:apply-templates select="wml:contentMeta/wml:titleGroup/wml:title[@type='main']" />
                </article-title>
            </title-group>
    </xsl:template>
    
    <xsl:template match="wml:creators">
        <contrib-group>
            <xsl:apply-templates />
        </contrib-group>
    </xsl:template>
    
    <xsl:template match="wml:creator">
        <contrib>
            <xsl:apply-templates />
            <xsl:variable name="rid" select="replace(@xml:id, 'cr', 'aff')"/>
            <xsl:if test="../../wml:affiliationGroup/wml:affiliation[@xml:id=$rid]">
                <xref>
                    <xsl:attribute name="ref-type">aff</xsl:attribute>
                    <!-- Turns a xml:id of journal12345-cr-0001 into journal12345-aff-0001 to match the structire in the affiliationGroup/affiliation[@xml:id]-->
                    <xsl:attribute name="rid"><xsl:value-of select="$rid"/></xsl:attribute>
                </xref>
            </xsl:if>
        </contrib>
    </xsl:template>
        
    <xsl:template match="wml:personName">
        <name name-style="western">
            <surname><xsl:value-of select="wml:familyName"/></surname>
            <given-names><xsl:value-of select="wml:givenNames"/></given-names>
        </name>
    </xsl:template>
    
    <xsl:template match="wml:biographyInfo">
        <bio>
            <p><xsl:value-of select='.'/></p>
        </bio>
    </xsl:template>
    
    <xsl:template match="wml:contactDetails/wml:email">
        <email>
            <xsl:value-of select='.'/>
        </email>
    </xsl:template>
    
    
    <xsl:template match="wml:creator/wml:idGroup/wml:id[@type='orcid']">
        <xsl:analyze-string select="@value" regex="([0-9]{{4}}-[0-9]{{4}}-[0-9]{{4}}-[0-9]{{3}}[0-9X]{{1}})">
            <xsl:matching-substring>
                <contrib-id contrib-id-type="orcid"><xsl:value-of select="regex-group(1)"/></contrib-id>
            </xsl:matching-substring>
        </xsl:analyze-string>
    </xsl:template>
    
    <xsl:template match="wml:affiliationGroup">
            <xsl:apply-templates/>
    </xsl:template>
    
    <xsl:template match="wml:affiliation">
        <aff>
            <!-- See contrib template to see how this is also set on xref:rid-->
            <xsl:attribute name="id"><xsl:value-of select="@xml:id"/></xsl:attribute>
            <xsl:value-of select="wml:orgDiv|wml:orgName|wml:address/wml:country" separator=", "/>
        </aff>
    </xsl:template>
    
    <xsl:template match="wml:publicationMeta[@level='unit']/wml:eventGroup/wml:event[@type='firstOnline']">
        <xsl:variable name="pubdate" select="@date"/>
        <pub-date publication-format="electronic">
            <xsl:attribute name="iso-8601-date"><xsl:value-of select="$pubdate"/></xsl:attribute>
            <xsl:for-each select="reverse(tokenize($pubdate, '-'))">
                <xsl:variable name="pos" select="position()"/>
                <xsl:element name="{$jats-date-parts/part[@idx=$pos]}"><xsl:value-of select="."/></xsl:element>
            </xsl:for-each>
        </pub-date>
    </xsl:template>
    
    <xsl:template name="issue-meta-block">
        <xsl:apply-templates select="wml:publicationMeta[@level='part']/wml:numberingGroup/wml:numbering"/>       
        <xsl:if test="wml:publicationMeta[@level='part']/wml:doi">
            <issue-id pub-id-type="doi">
                <xsl:value-of select="wml:publicationMeta[@level='part']/wml:doi"/>
            </issue-id>
        </xsl:if>
    </xsl:template>

    <xsl:template match="wml:numberingGroup/wml:numbering[@type='journalVolume']">
        <volume>
            <xsl:value-of select="./text()"/>
        </volume>
    </xsl:template>
    
    <xsl:template match="wml:numberingGroup/wml:numbering[@type='journalIssue']">
        <issue>
            <xsl:value-of select="./text()"/>
        </issue>
    </xsl:template>

    <xsl:template name="page-numbers-block">
        <xsl:if test="wml:publicationMeta[@level='unit']/wml:numberingGroup/wml:numbering[@type='pageFirst']">
            <fpage>
                <xsl:value-of select="wml:publicationMeta[@level='unit']/wml:numberingGroup/wml:numbering[@type='pageFirst']"/>
            </fpage>
        </xsl:if>    
        <xsl:if test="wml:publicationMeta[@level='unit']/wml:numberingGroup/wml:numbering[@type='pageLast']">
            <lpage>
                <xsl:value-of select="wml:publicationMeta[@level='unit']/wml:numberingGroup/wml:numbering[@type='pageLast']"/>
            </lpage>
        </xsl:if>    
    </xsl:template>

    <xsl:template match="wml:idGroup/wml:id[@type='unit']">
        <article-id>
            <xsl:value-of select="@value" />
        </article-id>
    </xsl:template>
    
    <xsl:template match="wml:titleGroup/wml:title[@type='main']"> 
        <xsl:value-of select="text()" />
    </xsl:template>
    
    <xsl:template name="permissions-block">
        <permissions>
            <xsl:apply-templates select="wml:publicationMeta[@level='unit']/wml:copyright"/>
            <xsl:apply-templates select="wml:publicationMeta/wml:legalStatement"/>
        </permissions>
    </xsl:template>
    
    <xsl:template match="wml:copyright">
        <copyright-statement><xsl:value-of select="."/></copyright-statement>
    </xsl:template>
    
    <xsl:template match="wml:legalStatement">
        <license license-type="open-access">
            <xsl:if test="./wml:p/wml:link/@href">
                <xsl:attribute name="xlink:href"><xsl:value-of select="replace(./wml:p/wml:link/@href, 'http://', 'https://')"/></xsl:attribute>
            </xsl:if>
            <license-p><xsl:value-of select="."/></license-p>
        </license>
    </xsl:template>
    
    <xsl:template match="wml:abstractGroup">
        <abstract>
            <xsl:apply-templates select="wml:abstract/wml:p"/>
        </abstract>
    </xsl:template>
    
    <xsl:template match="wml:p">
        <p>
            <xsl:value-of select="."/>
        </p>
    </xsl:template>
    
    <xsl:template match="wml:link">
        <uri>
            <xsl:attribute name="xlink:href"><xsl:value-of select="."/></xsl:attribute>
            <xsl:value-of select="."/>
        </uri>
    </xsl:template>
    
    <xsl:template match="wml:keywordGroup">
        <kwd-group>
            <xsl:apply-templates/>
        </kwd-group>
    </xsl:template>

    <xsl:template match="wml:keyword">
        <kwd>
            <xsl:apply-templates/>
        </kwd>
    </xsl:template>
    
    <xsl:template match="wml:contentMeta/wml:countGroup">
        <counts>
            <xsl:apply-templates/>
        </counts>
    </xsl:template>
    
    <xsl:template match="wml:contentMeta/wml:countGroup/wml:count[@type='figureTotal']">
        <fig-count>
            <xsl:attribute name="count"><xsl:value-of select="@number"/></xsl:attribute>
        </fig-count>        
    </xsl:template>
    
    <xsl:template match="wml:contentMeta/wml:countGroup/wml:count[@type='tableTotal']">
        <table-count>
            <xsl:attribute name="count"><xsl:value-of select="@number"/></xsl:attribute> 
        </table-count>        
    </xsl:template>
    
    <xsl:template match="wml:contentMeta/wml:countGroup/wml:count[@type='wordTotal']">
        <word-count>
            <xsl:attribute name="count"><xsl:value-of select="@number"/></xsl:attribute>           
        </word-count>        
    </xsl:template>

    <xsl:template match="wml:issn">
        <issn>
            <xsl:attribute name="pub-type">
                <xsl:value-of select="@type"/>
            </xsl:attribute>
            <xsl:value-of select="."/>
        </issn>
    </xsl:template>
    <!-- End JATS front -->

    <!-- Start JATS  body -->
    <xsl:template match="wml:body" >
        <body>
            <xsl:apply-templates/>
        </body>
    </xsl:template>

    <xsl:template match="wml:body//wml:p">
        <p><xsl:apply-templates/></p>
    </xsl:template>


    <xsl:template match="wml:body//wml:section">
        <sec>
            <xsl:if test="@xml:id">
                <xsl:attribute name="id"><xsl:value-of select="@xml:id"/></xsl:attribute>                
            </xsl:if>
            <xsl:apply-templates/>
        </sec>
    </xsl:template>
    
    <xsl:template match="wml:body//wml:section//wml:title">
        <title><xsl:apply-templates/></title>
    </xsl:template>
    
    <xsl:template match="wml:body//wml:label">
        <label><xsl:apply-templates/></label>
    </xsl:template>
    
    <xsl:template match="wml:body//wml:b">
        <bold><xsl:apply-templates/></bold>
    </xsl:template>
    
    <xsl:template match="wml:body//wml:i">
        <italic><xsl:apply-templates/></italic>
    </xsl:template>
    
    <xsl:template match="wml:body//wml:sup">
        <sup><xsl:apply-templates/></sup>
    </xsl:template>
    
    <xsl:template match="wml:body//wml:sub">
        <sub><xsl:apply-templates/></sub>
    </xsl:template>
    
    <xsl:template match="wml:body//wml:sc">
        <sc><xsl:apply-templates/></sc>
    </xsl:template>
    
    <xsl:template match="wml:body//wml:url">
        <ext-link>
            <xsl:attribute name="xlink:href"><xsl:value-of select="."/></xsl:attribute>
            <xsl:value-of select="."/>
        </ext-link>
    </xsl:template>
    
    <xsl:template match="wml:body//wml:email">
        <email><xsl:value-of select="."/></email>
    </xsl:template>
    
    <xsl:template match="wml:body//wml:figure">
        <fig>
            <xsl:if test="@xml:id">
                <xsl:attribute name="id"><xsl:value-of select="@xml:id"/></xsl:attribute>                
            </xsl:if>
            <xsl:apply-templates select="wml:label"/>
            <xsl:apply-templates select="wml:caption"/>
            <xsl:apply-templates select="wml:mediaResourceGroup/wml:mediaResource[@rendition='webOriginal']"/>
        </fig>
    </xsl:template>
    
    <xsl:template match="wml:body//wml:figure/wml:caption">
        <caption><xsl:apply-templates/></caption>
    </xsl:template>
    
    <xsl:template match="wml:body//wml:figure/wml:mediaResourceGroup/wml:mediaResource[@rendition='webOriginal']">
        <graphic>
            <xsl:attribute name="xlink:href"><xsl:value-of select="utils:getFilename(@href, '/')"/></xsl:attribute>
        </graphic>
    </xsl:template>
    
    <xsl:template match="wml:tabular|wml:tabularFixed">
        <table-wrap>
            <xsl:if test="@xml:id">
                <xsl:attribute name="id"><xsl:value-of select="@xml:id"/></xsl:attribute>                
            </xsl:if>
            <xsl:call-template name="table-caption"/>
            <xsl:apply-templates select="wml:table"/>
        </table-wrap>
    </xsl:template>
    
    <xsl:template name="table-caption">
        <xsl:apply-templates select="wml:label"/>
        <xsl:if test="wml:title">
            <caption>
                <xsl:apply-templates select="wml:title"/>
            </caption>
        </xsl:if>
        
    </xsl:template>
    <xsl:template match="wml:tabular/wml:table|wml:tabularFixed/wml:table">
        <xsl:if test="./wml:tgroup/wml:colspec">
            <table>
                <xsl:choose>
                    <xsl:when test="@frame='topbot'">
                        <xsl:attribute name="frame"><xsl:text>hsides</xsl:text></xsl:attribute>
                    </xsl:when>
                    <xsl:when test="@frame='void'">
                        <xsl:attribute name="frame"><xsl:text>hsides</xsl:text></xsl:attribute>
                    </xsl:when>  
                </xsl:choose>
                <colgroup>
                    <xsl:if test="./wml:tgroup/@align">
                        <xsl:attribute name="align"><xsl:value-of select="wml:tgroup/@align"/></xsl:attribute>
                    </xsl:if>          
                    <xsl:apply-templates select="wml:tgroup/wml:colspec"/>
                </colgroup>
                <xsl:apply-templates select="wml:tgroup/wml:thead"/>
                <xsl:apply-templates select="wml:tgroup/wml:tbody"/>
            </table>
        </xsl:if>
    </xsl:template>
    
    <xsl:template match="wml:tgroup/wml:colspec">
        <col>
            <xsl:if test="@align">
                <xsl:attribute name="align"><xsl:value-of select="@align"/></xsl:attribute>
            </xsl:if>
        </col>
    </xsl:template>
    
    <xsl:template match="wml:tgroup/wml:thead">
        <thead>
            <xsl:if test="@align">
                <xsl:attribute name="align"><xsl:value-of select="@align"/></xsl:attribute>
            </xsl:if>
            <xsl:if test="@valign">
                <xsl:attribute name="valign"><xsl:value-of select="@valign"/></xsl:attribute>
            </xsl:if>
            <xsl:apply-templates select="wml:row"/>
        </thead>
    </xsl:template>
    <xsl:template match="wml:tgroup/wml:tbody">
        <tbody>
            <xsl:if test="@align">
                <xsl:attribute name="align"><xsl:value-of select="@align"/></xsl:attribute>
            </xsl:if>
            <xsl:if test="@valign">
                <xsl:attribute name="valign"><xsl:value-of select="@valign"/></xsl:attribute>
            </xsl:if>
            <xsl:apply-templates select="wml:row"/>
        </tbody>
    </xsl:template>
    
    <xsl:template match="wml:thead/wml:row|wml:tbody/wml:row">
        <tr>
            <xsl:if test="@align">
                <xsl:attribute name="align"><xsl:value-of select="@align"/></xsl:attribute>
            </xsl:if>
            <xsl:if test="@valign">
                <xsl:attribute name="valign"><xsl:value-of select="@valign"/></xsl:attribute>
            </xsl:if>
            <xsl:apply-templates select="wml:entry"/>
        </tr>
    </xsl:template>
    
    <xsl:template match="wml:thead/wml:row/wml:entry">
        <th>
            <xsl:if test="@align">
                <xsl:attribute name="align"><xsl:value-of select="@align"/></xsl:attribute>
            </xsl:if>
            <xsl:if test="@valign">
                <xsl:attribute name="valign"><xsl:value-of select="@valign"/></xsl:attribute>
            </xsl:if>
            <xsl:apply-templates/>
        </th>
    </xsl:template>
    
    <xsl:template match="wml:tbody/wml:row/wml:entry">
        <td>
            <xsl:if test="@align">
                <xsl:attribute name="align"><xsl:value-of select="@align"/></xsl:attribute>
            </xsl:if>
            <xsl:if test="@valign">
                <xsl:attribute name="valign"><xsl:value-of select="@valign"/></xsl:attribute>
            </xsl:if>
            <xsl:apply-templates/>
        </td>
    </xsl:template>
    
    <!-- End JATS body -->
    
    <!-- Start utility functions -->
    <xsl:function name="utils:getFilename">
        <xsl:param name="str"/>
        <!--str e.g. document-uri(.), filename and path-->
        <xsl:param name="char"/>
        <xsl:value-of select="subsequence(reverse(tokenize($str, $char)), 1, 1)"/>
    </xsl:function>
    <!-- End utility functions -->
    
</xsl:stylesheet>