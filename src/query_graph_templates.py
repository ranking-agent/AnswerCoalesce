def qg_template():
    return '''{
        "query_graph": {
            "nodes": {
                "$source": {
                    "ids": $source_id,
                    "is_set": false,
                    "categories":  $source_category
                },
                "$target": {
                    "ids": $target_id,
                    "is_set": true,
                    "constraints": [],
                    "categories": $target_category
                    }
            },
            "edges": {
                "e00": {
                    "subject": "$source",
                    "object": "$target",
                    "predicates":
                        $predicate
                    ,
                    "attribute_constraints": [],
                    "qualifier_constraints": $qualifier

                }
            }
        }
    }
'''