"""Experiment workflow using the verified snapshot schema and isolated storage."""
import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from storage import export_records, import_records, make_record, restore_record
from ui import comparison_table
from workflow import analysis_version


def save_batch(records, store, session_records):
    """Persist a validated batch; validation/replay is done before this boundary."""
    if store:
        store.save_many(records)
    else:
        for record in records:
            session_records.setdefault(record['id'],record)


def import_batch(raw, store, session_records):
    records=import_records(raw)
    save_batch(records,store,session_records)
    return len(records)


def make_active_record(name, active):
    record=make_record(name,active['config'],active['prices'],active['results'],active['notes'],active['calculated_at'])
    if 'features' in active:
        from website_features import snapshot_for
        record.update(version=2, research=json.loads(snapshot_for(active)))
    return record


def save_panel(active, store, blocked, view_saved=None):
    """One naming/save flow shared by the direct dialog and the library page."""
    config,prices,results=active['config'],active['prices'],active['results']
    if store:
        st.info('Save to local storage on this computer. Records survive restarts. Download JSON for a portable backup.')
    else:
        st.info('Save to this browser session only. Records may be lost after a refresh, disconnect or restart. Download JSON to keep and restore your experiment. Permanent cloud storage is not provided.')
    st.caption('The snapshot includes applied settings, price and benchmark snapshots, indicators, all enabled strategies and every execution.')
    def name_changed():
        st.session_state.saved_name_draft=st.session_state.experiment_name
    st.text_input('Experiment name',max_chars=80,key='experiment_name',on_change=name_changed)
    if blocked:
        st.warning('Apply your changes first, or restore the applied settings before saving.')
    if st.button('Save to local storage' if store else 'Save to this session',type='primary',disabled=blocked,key='save_snapshot'):
        try:
            record=make_active_record(st.session_state.experiment_name,active)
            save_batch([record],store,st.session_state.session_records)
            version=analysis_version(active)
            st.session_state.progress_by_version[version].add('Saved experiments')
            st.session_state.completed=set(st.session_state.progress_by_version[version])
            st.session_state.last_saved={'version':version, 'record':record}
            st.session_state.pop('save_error',None)
            st.rerun()
        except ValueError as exc:
            st.session_state.save_error='Save failed: '+str(exc)
        except OSError as exc:
            st.session_state.save_error='Save failed: '+str(exc)+'. Check local storage access and retry.'
        except Exception:
            st.session_state.save_error='Save failed: storage could not accept the snapshot. Retry, or download the applied analysis from Saved experiments.'
    if st.session_state.get('save_error'):
        st.error(st.session_state.save_error)
    saved=st.session_state.get('last_saved')
    if saved and saved['version']==analysis_version(active):
        record=saved['record']
        st.success(f'Saved “{record["name"]}”'+(' to local storage.' if store else ' to this session.'))
        st.download_button('Download JSON',export_records([record]),file_name=f'portfolio-lab-{record["id"][:8]}.json',
                           mime='application/json',type='primary',width='stretch')
        def default_view():
            st.session_state.update(page='Saved experiments',show_save=False)
        if st.button('View saved experiments',on_click=view_saved or default_view,width='stretch'):
            # A dialog normally reruns only its fragment. Navigation must close
            # the dialog and render the destination in the full application.
            st.rerun(scope='app')


def experiment_page(active, store, blocked, show_form=True):
    config,prices,results=active['config'],active['prices'],active['results']
    if 'experiment_notice' in st.session_state:
        st.success(st.session_state.pop('experiment_notice'))
    if show_form:
        st.subheader('Save a reproducible experiment')
        save_panel(active,store,blocked)
    current=make_active_record('Current analysis',active)
    st.download_button('Export applied analysis · JSON',export_records([current]),file_name='portfolio-lab-current.json',mime='application/json')
    st.caption('This download contains the displayed, applied results even if draft settings have changed.')
    try:
        records=([store.get(r['id']) for r in store.list_records()] if store else
                 sorted(st.session_state.session_records.values(),key=lambda r:r['created_at'],reverse=True))
    except Exception:
        records=[]
        st.error('Could not read saved experiments. Check local storage; current results remain available.')
    st.divider()
    st.subheader(f'Saved experiments · {len(records)}')
    if not records:
        st.info('No saved experiments yet. Name the applied analysis and save it, or import a Portfolio Lab JSON file.')
    else:
        rows=[{'Experiment':r['name'],'Saved (HKT)':datetime.fromisoformat(r['created_at']).astimezone(ZoneInfo('Asia/Hong_Kong')).strftime('%Y-%m-%d %H:%M'),
               'Source':'Synthetic demo' if r['config']['source']=='demo' else 'Yahoo history',
               'Stocks':', '.join(r['config']['symbols']),'Capital (USD)':r['config']['capital']} for r in records]
        st.caption('Swipe or scroll the table horizontally → · Use the table fullscreen control for more room.')
        st.dataframe(pd.DataFrame(rows).style.format({'Capital (USD)':'${:,.2f}'}),hide_index=True,width='stretch')
        by_id={r['id']:r for r in records}
        label=lambda rid:by_id[rid]['name']+' · '+rid[:8]
        selected=st.selectbox('Select a saved experiment',list(by_id),format_func=label,key='open_record')
        def open_history():
            st.session_state.pending_record=by_id[selected]
            st.session_state.page='Overview'
        c1,c2=st.columns(2)
        c1.button('Open full results',on_click=open_history,width='stretch')
        c2.download_button('Download selected · JSON',export_records([by_id[selected]]),file_name=f'portfolio-lab-{selected[:8]}.json',mime='application/json',width='stretch')
        st.subheader('Compare two experiments')
        compare=st.multiselect('Select two records',list(by_id),format_func=label,max_selections=2,key='compare_records')
        if len(compare)==2:
            a,b=(by_id[i] for i in compare)
            ca,cb=a['config'],b['config']
            field_names={'symbols':'Stocks','weights':'Weights (%)','capital':'Initial capital (USD)','start':'Start date','end':'End date','source':'Data source',
                'short_window':'Short MA','long_window':'Long MA','take_profit':'Take profit','stop_loss':'Stop loss','max_hold_days':'Max holding days','fee':'One-way fee'}
            different=[title for key,title in field_names.items() if ca[key]!=cb[key]]
            if a['results']['hold']['dates']!=b['results']['hold']['dates']:different.append('Effective period')
            if a['prices']!=b['prices']:different.append('Price snapshot')
            if different:
                st.warning('The experiments differ in: '+', '.join(different)+'. Compare these assumptions before interpreting their performance.')
            else:
                st.caption('Matched configuration and price snapshot. All stored strategies are shown below.')
            def display(key,value):
                if key in ('take_profit','stop_loss','fee'):return f'{value:.2%}'
                if key=='source':return 'Synthetic demo' if value=='demo' else 'Yahoo history'
                return ', '.join(map(str,value)) if isinstance(value,list) else str(value)
            params=[{'Parameter':title,'Experiment A':display(k,ca[k]),'Experiment B':display(k,cb[k]),'Status':'Same' if ca[k]==cb[k] else 'Different'} for k,title in field_names.items()]
            st.dataframe(pd.DataFrame(params),hide_index=True,width='stretch')
            for column,record in zip(st.columns(2),[a,b]):
                with column:
                    st.write(record['name'])
                    _,_,restored=restore_record(record)
                    comparison_table(restored)
        elif compare:
            st.caption('Select one more record to compare assumptions and all three strategies.')
        with st.expander('Batch export & remove'):
            exports=st.multiselect('Batch export (up to 20 records)',list(by_id),format_func=label,max_selections=20,key='batch_records')
            if exports:
                try:
                    st.download_button('Download selected archive · JSON',export_records([by_id[i] for i in exports]),file_name='portfolio-lab-archive.json',mime='application/json')
                except ValueError as exc:st.error(str(exc))
            confirm=st.checkbox('Remove the selected experiment from this library',key='confirm_remove')
            st.caption('Download it first if you want a copy. Removing it does not change the displayed analysis.')
            if st.button('Remove selected experiment',disabled=not confirm,key='remove_record'):
                try:
                    if store:store.delete(selected)
                    else:st.session_state.session_records.pop(selected,None)
                    st.session_state.pop('open_record',None)
                    st.session_state.pop('compare_records',None)
                    st.session_state.pop('batch_records',None)
                    st.session_state.pop('confirm_remove',None)
                    st.session_state.experiment_notice='Selected experiment removed from this library.'
                    st.rerun()
                except Exception:
                    st.error('Could not remove the experiment. Check local storage access.')
    st.divider()
    st.subheader('Import experiments')
    st.caption('Portfolio Lab JSON · up to 8 MB and 20 records · every snapshot is validated and replayed before import. Existing IDs are skipped.')
    uploaded=st.file_uploader('Choose a Portfolio Lab JSON file',type=['json'],key='import_file')
    if st.button('Validate & import',disabled=uploaded is None,key='import_records'):
        try:
            with st.spinner('Validating snapshots and replaying results…'):
                count=import_batch(uploaded.getvalue(),store,st.session_state.session_records)
            st.session_state.experiment_notice=f'Processed {count} valid experiments. Existing IDs were skipped.'
            st.rerun()
        except ValueError as exc:st.error('Import failed: '+str(exc))
        except Exception:st.error('Import failed. Use a valid Portfolio Lab JSON export and check storage access.')
