# impedance plots
# for loop EIS make plot for all, get the cell constant for each
# from the jsons extract conductivity and and resistance
# copy the current dataFrame and add predicted conductivity and resistance
# headers are ;experimentID;electrolyteLabel;PC;EC;EMC;LiPF6;inverseTemperature;temperature;conductivity;resistance;Z';Z'';frequency;electrolyteAmount
# plot conductivity vs. (EC/PC) colorbar (LiPF6/EMC)
# add default and get circuits to the dataFrame
from functools import cache
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir)))
from joblib import Parallel, delayed
from joblib import Memory
import re
from tqdm import tqdm
import pandas as pd
import matplotlib

from madap.plotting import plotting
from madap.echem.e_impedance import e_impedance as imp
from madap.data_acquisition import data_acquisition as da

# 1. train with custom circuit and no initial value
# 2. train with default circuit and no initial value
# 3. train with default circuit and with initial value
# 4. train with default circuit and with initial value and with outlier detection
# 5. train with custom circuit and outlier detection


name = "default_initial" #["default", "custom", "default_initial", "defualt_initial_outliers", "custom_outliers"]

# cache the function
location = fr"figures_creation/cache_dir_{name}"
memory = Memory(location, verbose=True)

#matplotlib.use('Agg')
matplotlib.rcParams["figure.max_open_warning"] = 1500

DEFAULTTRAIN = False
DEFAULTTRAINWITHINITIALVALUE = True
DEFAULTTRAINWITHOUTLIER = False
CUSTOMTRAIN = False

plotting.Plots()
save_dir = os.path.join(os.getcwd(), fr"electrolyte_figures/impedance_{name}")

plot_type = ["nyquist" ,"nyquist_fit", "residual", "bode"]

# load the data
data = pd.read_csv(os.path.join(os.getcwd(),r"data/Dataframe_STRUCTURED_all508.csv"), sep=";")
del data['Unnamed: 0']
temperatures = data["temperature [°C]"].unique().tolist()
temperatures.sort()

local_data = data

def get_data_from_dataframe(data, exp_id, temp, ind_data, phase_shift = False):
    freq_data = eval(data.loc[(data["experimentID"] == exp_id) & (data["temperature [°C]"] == temp), "frequency [Hz]"][ind_data])
    real_data = eval(data.loc[(data["experimentID"] == exp_id) & (data["temperature [°C]"] == temp), "real impedance Z' [Ohm]"][ind_data])
    imag_data = eval(data.loc[(data["experimentID"] == exp_id) & (data["temperature [°C]"] == temp), "imaginary impedance Z'' [Ohm]"][ind_data])
    cell_constant = float(re.findall(r'\b(\d*\.?\d+)', data.loc[(data["experimentID"] == exp_id) & (data["temperature [°C]"] == temp), "cell constant, standard deviation"][ind_data])[0])

    if phase_shift:
        phase_shift_data = eval(data.loc[(data["experimentID"] == exp_id) & (data["temperature [°C]"] == temp), "phase_shift \u03c6 [\u00b0]"][ind_data])
    else:
        phase_shift_data = None

    return freq_data, real_data, imag_data, cell_constant, phase_shift_data


def eis_procedure(freq_data, real_data, imag_data, phase_shift_data, suggested_circuit, initial_value, cell_constant,plot_type, exp_id, temp):

    # initialize the Impedance class
    Im = imp.EImpedance(da.format_data(freq_data), da.format_data(real_data), da.format_data(imag_data), phase_shift_data)

    # initialis the EIS procedure
    Eis  = imp.EIS(Im, voltage=None, suggested_circuit=suggested_circuit,
                            initial_value=initial_value, cell_constant = cell_constant)
    # analyze the data
    Eis.perform_all_actions(save_dir, plots = da.format_plots(plot_type), optional_name=f"{exp_id}_{temp}")

    return Eis

def concat_new_data(Eis, data, exp_id, temp, analysis_type = "default", phase_shift = False):
    if phase_shift:
        #1. phase_shift
        data.loc[(data["experimentID"] == exp_id) & (data["temperature [°C]"] == temp), "phase_shift \u03c6 [\u00b0]"] = str(Eis.impedance.phase_shift)
    #2. conductivity
    data.loc[(data["experimentID"] == exp_id) & (data["temperature [°C]"] == temp), f"madap_conductivity_{analysis_type} [S/cm]"] = Eis.conductivity
    #3. parameters plus theirs errors/confidance
    data.loc[(data["experimentID"] == exp_id) & (data["temperature [°C]"] == temp), f"madap_fit_params_{analysis_type}"] = str([(val, err) for val, err in zip(Eis.custom_circuit.parameters_, Eis.custom_circuit.conf_)])
    #4. RMSE of the fit
    data.loc[(data["experimentID"] == exp_id) & (data["temperature [°C]"] == temp), f"madap_rmse_{analysis_type}"] = Eis.rmse_calc
    #5. num_rc_linKK
    data.loc[(data["experimentID"] == exp_id) & (data["temperature [°C]"] == temp), f"madap_num_rc_linKK_{analysis_type}"] = Eis.num_rc_linkk
    #6. eval_fit_linKK
    data.loc[(data["experimentID"] == exp_id) & (data["temperature [°C]"] == temp), f"madap_eval_fit_linKK_{analysis_type}"] = Eis.eval_fit_linkk
    #7. resistance [Ohm]
    data.loc[(data["experimentID"] == exp_id) & (data["temperature [°C]"] == temp), f"madap_resistance_{analysis_type} [Ohm]"]=  Eis.custom_circuit.parameters_[0]
    #8 chi_value
    data.loc[(data["experimentID"] == exp_id) & (data["temperature [°C]"] == temp), f"madap_chi_square_{analysis_type}"] = Eis.chi_val
    # predicted data
    data.loc[(data["experimentID"] == exp_id) & (data["temperature [°C]"] == temp), f"predicted_impedance_{analysis_type} [Ohm]"] = str(Eis.z_fit.tolist())
    # real residual
    data.loc[(data["experimentID"] == exp_id) & (data["temperature [°C]"] == temp), f"residual_real_{analysis_type} [Ohm]"] = str(Eis.res_real)
    # imaginary residual
    data.loc[(data["experimentID"] == exp_id) & (data["temperature [°C]"] == temp), f"residual_imaginary_{analysis_type} [Ohm]"] = str(Eis.res_imag)
    # custom circuit
    data.loc[(data["experimentID"] == exp_id) & (data["temperature [°C]"] == temp), f"custom_circuit_{analysis_type}"] = str(Eis.custom_circuit)

# ---------------------- Train with default circtuit ----------------------

# one time train without a custom circuit and with the default circuit
# suggested_circuit="R0-p(R1,CPE1)"
# initial_value=[800,1e+14,1e-9,0.8]
# PVA_30032021_BM072_1
# ind_data = 246


def constly_compute(data, exp_id):
    #r0_index = 0
    for temp in temperatures:

        if len(data.loc[(data["experimentID"] == exp_id) & (data["temperature [°C]"] == temp), "frequency [Hz]"]) != 0:

            ind_data = data.loc[(data["experimentID"] == exp_id) & (data["temperature [°C]"] == temp), "frequency [Hz]"].index[0]
            print(f"The index is {ind_data}")
            freq_data, real_data, imag_data, cell_constant, phase_shift_data = get_data_from_dataframe(data, exp_id, temp, ind_data, phase_shift = False)

            if DEFAULTTRAIN:

                Eis = eis_procedure(freq_data, real_data, imag_data, phase_shift_data, suggested_circuit = "R0-p(R1,CPE1)",
                                        initial_value = [800,1e+14,1e-9,0.8], cell_constant = cell_constant,
                                        plot_type = plot_type, exp_id= exp_id, temp = temp)

            if CUSTOMTRAIN:
                Eis = eis_procedure(freq_data, real_data, imag_data, phase_shift_data, suggested_circuit = None,
                                        initial_value = None, cell_constant = cell_constant,
                                        plot_type = plot_type, exp_id = exp_id, temp = temp)

            if DEFAULTTRAINWITHINITIALVALUE:
                r0_index = data.loc[(data["experimentID"] == exp_id) & (data["temperature [°C]"] == temp), "real impedance Z' [Ohm]"].index[0]
                r0_guess = eval(data.loc[(data["experimentID"] == exp_id) & (data["temperature [°C]"] == temp), "real impedance Z' [Ohm]"][r0_index])[0]
                Eis = eis_procedure(freq_data, real_data, imag_data, phase_shift_data, suggested_circuit = "R0-p(R1,CPE1)",
                                        initial_value = [r0_guess,1e+14,1e-9,0.8], cell_constant = cell_constant,
                                        plot_type = plot_type, exp_id = exp_id, temp = temp)

constly_compute_cached = memory.cache(constly_compute)

def data_processing_using_cache(data, exp_id):
    return constly_compute_cached(data, exp_id)

results = Parallel(n_jobs=30)(delayed(data_processing_using_cache)(data, exp_id) for exp_id in tqdm(data["experimentID"].unique()))
