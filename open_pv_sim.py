import dash
from dash import dcc, html, Input, Output
from dash.dependencies import Input, Output, State
from dash.exceptions import PreventUpdate
import plotly.graph_objs as go
import pandas as pd
import numpy as np
import requests
import datetime


# Modules for PV panels
import pvlib
from pvlib.temperature import TEMPERATURE_MODEL_PARAMETERS
from pvlib.pvsystem import PVSystem, FixedMount
from pvlib.modelchain import ModelChain

def lv95ToWgs84(x,y):
    """
    Convert swiss coordinates (LV03) to latitude, longitude values (WGS84)
    https://www.swisstopo.admin.ch › ch1903wgs84_d

    Parameters
    ----------
    x : float
        lv95 x coordinate
    y : float
        lv95 y coordinate

    Result
    ---------
    lat : float
        latitude
    lon : float
        longitude

    """
    ys=(x-2600000)/1000000 #LV95
    xs=(y-1200000)/1000000  #LV95
    lon=2.6779094+4.728982*ys+0.791484*ys*xs+0.1306*ys*xs*xs-0.0436*ys*ys*ys
    lat=16.9023892+3.238272*xs-0.270978*ys*ys-0.002528*xs*xs-0.0447*ys*ys*xs-0.0140*xs*xs*xs
    lon=lon*100/36
    lat=lat*100/36
    if np.isnan(lon) or np.isnan(lat):
        return None
    else:
        return (lat,lon)

def get_coordinates(adress):

    url_1 = "https://api3.geo.admin.ch//rest/services/api/SearchServer?lang=de&searchText="+adress+"&type=locations&sr=2056"
    response = requests.get(url_1).json()
    try:
        y = response['results'][0]['attrs']['y']
        x = response['results'][0]['attrs']['x']
        coord = str(y)+","+str(x)
    except:
        print("Error loading Adress")
    lat, lon = lv95ToWgs84(y,x)

    return coord,lat,lon

def get_building_id(coord):

    url_2= "https://api3.geo.admin.ch//rest/services/api/MapServer/identify?geometryType=esriGeometryPoint&returnGeometry=true&layers=all:ch.bfe.solarenergie-eignung-daecher&geometry="+coord+"&tolerance=0&order=distance&lang=de&sr=2056"
    response = requests.get(url_2).json()
    try:
        building_id = response['results'][0]['attributes']['building_id']
    except:
        print("Error loading coordinates"+coord)

    return building_id

def get_sonnendach(building_id): 
    feature_ids=[]
    pv_class=[]
    ausrichtung=[]
    pv_yield=[]
    neigung=[]
    area=[]
    building_ids=[]

    url_3 = "https://api3.geo.admin.ch//rest/services/api/MapServer/find?layer=ch.bfe.solarenergie-eignung-daecher&searchField=building_id&searchText="+str(building_id)+"&contains=false"
    response = requests.get(url_3).json()
    
    for idx, num in enumerate(response['results']):
        feature_id = response['results'][idx]['featureId']   
        if feature_id not in feature_ids:
            feature_ids.append(feature_id)
            building_ids.append(building_id)
            pv_class.append(response['results'][idx]['attributes']['klasse'])
            ausrichtung.append(response['results'][idx]['attributes']['ausrichtung'])
            pv_yield.append(response['results'][idx]['attributes']['stromertrag'])
            neigung.append(response['results'][idx]['attributes']['neigung'])
            area.append(response['results'][idx]['attributes']['flaeche'])

    df = pd.DataFrame([building_ids,feature_ids,pv_class,ausrichtung,pv_yield,neigung,area]).transpose()
    df.columns=['building_ids','feature_ids','PV_klasse','ausrichtung','Stromertrag','neigung','area']
    return df

def pv_sim(lat,lon,roof_info):
    usefull_roof_area = 1
    PR = 0.85

    weather = pvlib.iotools.get_pvgis_tmy(lat,lon,map_variables=True)[0]
    mod_lib = pvlib.pvsystem.retrieve_sam('cecmod')
    modules = mod_lib['Jinko_Solar__Co___Ltd_JKM385M_72L'] # average module with efficiency of 20%
    location = pvlib.location.Location(latitude=lat, longitude=lon)
    cec_inverters = pvlib.pvsystem.retrieve_sam('cecinverter')
    cec_inverter = cec_inverters['ABB__MICRO_0_25_I_OUTD_US_208__208V_'] # not really needed (since DC output is used later)
    temperature_model_parameters = TEMPERATURE_MODEL_PARAMETERS['sapm']['open_rack_glass_glass']

    system = PVSystem(surface_tilt=roof_info.neigung, 
                        surface_azimuth=roof_info.ausrichtung+180,
                        module_parameters=modules,
                        inverter_parameters=cec_inverter,
                        temperature_model_parameters=temperature_model_parameters)

    mc = ModelChain(system, location, aoi_model="no_loss",spectral_model="no_loss") # high-level interface for standardized PV modeling
    mc.run_model(weather)

    res = mc.results.dc.p_mp/modules.A_c/1000*(roof_info.area*usefull_roof_area)*PR #kW/usefull_roof_area
    ac_power = pd.DataFrame(list(res),columns=['Power_kW'])
    
    start =datetime.datetime(2022,1,1,0)
    end =datetime.datetime(2022,12,31,23)
    ac_power.index = pd.date_range(start,end,freq='1H')

    return ac_power





if __name__=="__main__":
    


    app = dash.Dash(__name__)
    feature_options=['Dach1','Dach2']
    roof_info={}

    app.layout = html.Div(
        children=[
        dcc.Input(id='streetname', type='text', placeholder="Strassenname",style={'marginRight':'20px'},required=True),
        dcc.Input(id='streetnumber', type='number',placeholder="Strassen Nr.",style={'marginRight':'20px'}),
        dcc.Input(id='plz', type='number',placeholder="PLZ",style={'marginRight':'20px'}),
        dcc.Input(id='townname', type='text',placeholder="Ort",style={'marginRight':'20px'}),

        html.Button(id='submit-button', type='submit', children='Submit'),
        
        html.H2("Folgende Dachflächen wurden an dieser Andresse gefunden:"),
        dcc.Checklist(
            id='feature_id',
            options=[
                {"label": 'roof1',"value":'0'},
            ],
            value=[],
            inline=True
        ),

        html.Button(id='submit-button-2', type='submit', children='Submit'),

        
        html.Div(id='output_div'),
        html.Div(id='output_pv')

        #html.Iframe(src="https://map.geo.admin.ch/?lang=de&topic=energie&bgLayer=ch.swisstopo.swissimage&catalogNodes=2419,2420,2427,2480,2429,2431,2434,2436,2767,2441,3206&layers=ch.bfe.solarenergie-eignung-daecher&zoom=22&X=234885&Y=675658&layers_opacity=0.65",
        #        style={"height": "1067px", "width": "100%"})

    ])

    
    @app.callback(Output('output_div', 'children'),
                Output('feature_id','options'),
                Input('submit-button', 'n_clicks'),
                Input("streetname", "value"),
                Input("streetnumber", "value"),
                Input("plz", "value"),
                Input("townname", "value"),
                  )
    def update_output(clicks, streetname,streetnumber,plz,townname):
        if clicks is not None:
            #print(clicks, streetname)
            adress = streetname+"%20"+str(streetnumber)+"%20"+str(plz)+"%20"+townname
            coord,lat,lon = get_coordinates(adress)
            building_id = get_building_id(coord)
            df = get_sonnendach(building_id)
            feature_options = list(df.feature_ids)
            
            # store roof info in dictionary
            
            for i in range(0,len(df)):
                roof_info[df.iloc[i].feature_ids]=df.iloc[i]

            return [],feature_options
        
        else:
            return [],[]

    @app.callback(Output('output_pv', 'children'),
                Input('submit-button-2', 'n_clicks'),
                Input('feature_id','value')
                  )
    def selected_roof(clicks,feature_id):
        
        if clicks is not None:
            print(feature_id)
            for id in feature_id:
                selected_roof = roof_info[id]
                print(selected_roof)
        



    app.run_server(debug=True)