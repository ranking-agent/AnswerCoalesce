# run with:
#  panel serve enrich_view.py --show --autoreload

import panel as pn
import os
import json
import pandas as pd
import re
from matplotlib import gridspec
import param
import holoviews as hv
from bokeh.models.widgets.tables import ScientificFormatter
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LogNorm, Normalize
from matplotlib.cm import ScalarMappable
from textwrap import wrap
from matplotlib.ticker import MultipleLocator

from collections import defaultdict

pn.extension("tabulator")

# Create and populate the data chooser
files = os.listdir(".")
jsons = [f for f in files if f.endswith(".json")]
jsons.sort()
jsons = [""]+jsons


## This is going to be the parsed input file in a way that makes it easy to access the data and control the view
class Data(param.Parameterized):
    response = param.Dict({})
    results = param.DataFrame(pd.DataFrame({}))
    enrichments = param.DataFrame(pd.DataFrame({}))
    data_select = param.ObjectSelector(default="",objects=jsons)

    @param.depends()
    def __init__(self, **params):
        super().__init__(**params)
        files = os.listdir(".")
        jsons = [f for f in files if f.endswith(".json")]
        jsons.sort()
        self.jsons = [""] + jsons

    @param.depends("results")
    def result_table(self):
        dx = self.results
        self.rtable = pn.widgets.Tabulator(
            dx,
            selectable=1,
            show_index=False,
            editors={'identifier':None, 'enrichment_names': None, 'p_values': None, 'supporting_study_cohort': None,
                     'object_aspect_qualifier': None, 'object_direction_qualifier': None, 'predicate': None, 'enrichment_type': None, 'enriched':None, 'enriched_names':None,},
            formatters={"p_values": ScientificFormatter()}
        )
        return self.rtable


    @param.depends('data_select', watch=True)
    def load_select(self):
        if self.data_select == "":
            return
        filename = self.data_select
        with open(filename, "r") as inf:
            self.response=json.load(inf)
        self.get_results()

    def getsetlabel(self):
        res = self.response
        res['query_graph']['node']

    def get_results(self):
        results = self.response.get("results",{})
        for qid, node_data in self.response["query_graph"]['nodes'].items():
            if "ids" in node_data and node_data['is_set']:
                aid=qid
            else:
                qgid = qid

        reslt = []
        for result in results:
            identifier = [x['id'] for x in result['node_bindings'][qgid]][0]
            names = self.response["knowledge_graph"]["nodes"][identifier]["name"]
            types = self.response["knowledge_graph"]["nodes"][identifier]["categories"][0]
            for att in result["analyses"][0]["attributes"]:
                if att["attribute_type_id"] == "biolink:p_value":
                    p_values = att.get("value", '')
                if att["attribute_type_id"] == "biolink:supporting_study_cohort":
                    supporting_study_cohort = att.get("value", '')
                if att["attribute_type_id"] == "biolink:object_aspect_qualifier":
                    object_aspect_qualifier = att.get("value", '')
                if att["attribute_type_id"] == "biolink:object_direction_qualifier":
                    object_direction_qualifier = att.get("value", '')
                if att["attribute_type_id"] == "biolink:predicate":
                    predicate = att["value"]
            rex = [x['id'] for x in result['node_bindings'][aid]]
            rxtype = [self.response.get("knowledge_graph", {}).get("nodes", {})[rx]["name"] for rx in rex]
            reslt.append([identifier, names, p_values, supporting_study_cohort, object_aspect_qualifier, object_direction_qualifier, predicate,  types, rex, rxtype])

        df = pd.DataFrame(reslt, columns = ['identifier', 'enrichment_names', 'p_values', 'supporting_study_cohort', 'object_aspect_qualifier', 'object_direction_qualifier', 'predicate', 'enrichment_type', 'enriched', 'enriched_names'])
        # df.drop_duplicates(inplace=True, ignore_index=True)
        df.sort_values(by="p_values", ascending=False, inplace=True)


        self.results = df


    @param.depends('results')
    def create_plot(self):
        # plt.rcParams["figure.autolayout"] = True
        data = self.results
        title = 'Enrichment Plot'
        n = 20
        j=data.shape[0]
        if data.shape[0]>20:
            data = data.head(20)
            title = 'Sample 20 Enrichment Plot'
            j=20

        if not data.empty:

            mask = data['enrichment_names'].duplicated(keep=False)
            data.loc[mask, 'enrichment_names'] += data.groupby('enrichment_names').cumcount().add(1).astype(str)

            # Flatten the data to create individual rows for each combination of name and source
            flat_data = [(name, source, value) for name, sources, value in
                         zip(data['enrichment_names'], data['enriched'], data['p_values']) for
                         source in sources]

            names = set(item[0] for item in flat_data)
            name_to_sources = {name: set() for name in names}
            name_to_value = {name: 0 for name in names}

            for name, source, value in flat_data:
                name_to_sources[name].add(source)
                name_to_value[name] += value

            sorted_names = sorted(names, key=lambda name: name_to_value[name], reverse=True)
            # print(sorted_names)
            name_indices = np.arange(len(sorted_names))
            values = [name_to_value[name] for name in sorted_names]
            bubble_sizes = [len(name_to_sources[name]) for name in sorted_names]
            # print(bubble_sizes)
            fig, ax = plt.subplots(figsize=(18, j))
            gs = gridspec.GridSpec(1, 2, width_ratios=[12,1])
            ax = plt.subplot(gs[0])
            cmap = plt.get_cmap('seismic')
            norm = Normalize(vmin=min(values), vmax=max(values))
            colors = [cmap(norm(value)) for value in values]

            scatter = ax.scatter(values, name_indices, c=colors, alpha=0.7, edgecolors='w',
                                 s=np.array(bubble_sizes) * n,
                                 label='# fo Genes')

            ax.set_xlabel('Normalized PValue')
            ax.set_ylabel('Name')
            ax.set_yticks(name_indices)
            ax.set_yticklabels(['\n'.join(wrap(i, 30)) for i in sorted_names], fontsize = 10, ha='right')
            # ax.invert_yaxis()
            ax.yaxis.set_tick_params(pad=20)
            ax.grid(linewidth=0.1)
            ax.set_title(title)


            handles, labels = scatter.legend_elements("sizes", num=5)
            # new_label = []
            # new_handle = []
            # print(handles, labels)
            rc = r'\d+'

            labels = set(f"${int(re.search(rc, label).group()) // n}$" for label in labels)
            legend = ax.legend(handles, labels, title="# of Genes",
                               bbox_to_anchor=(1.1, 0.6))
            ax.add_artist(legend)

            cax = plt.subplot(gs[1])
            sm = ScalarMappable(cmap=cmap, norm=norm)
            sm.set_array([])

            cbar = plt.colorbar(sm, orientation='vertical', cax=cax)
            cbar.set_label('Min-Max Normalized P-value')

            plot_panel = pn.pane.Matplotlib(fig, width=1000, height=400)
            return plot_panel

    @param.depends('results')
    def pieplot(self):
        import random
        data = self.results
        if not data.empty:
            if len(set(data['enrichment_type'])) > 1:
                fig, ax = plt.subplots(figsize=(4, 4))
                ax.pie(data['enrichment_type'].value_counts().values,
                       labels=data['enrichment_type'].value_counts().index, autopct='%1.1f%%',pctdistance=0.65,
                       radius=1)

                plt.show()
                pie_pane = pn.pane.Matplotlib(fig)
                return pie_pane

data = Data()


row = pn.Row(data.result_table)
plot_panel = pn.Row(data.create_plot)
plot_panel2 = pn.Row(data.pieplot)

layout = pn.Column(data.param.data_select, row, plot_panel, plot_panel2)

layout.servable()
