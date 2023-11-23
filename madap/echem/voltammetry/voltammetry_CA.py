import numpy as np
from scipy.stats import linregress
import scipy.constants as const

from madap.echem.voltammetry.voltammetry import Voltammetry
from madap.echem.procedure import EChemProcedure
from madap.logger import logger

log = logger.get_logger("cyclic_amperometry")


class Voltammetry_CA(Voltammetry, EChemProcedure):
    """ This class defines the chrono amperometry method."""
    def __init__(self, current, voltage, time, args, charge:list[float]=None) -> None:
        super().__init__(voltage, current, time, args.measured_current_units, args.measured_time_units, args.number_of_electrons)
        self.applied_voltage = float(args.applied_voltage) # Unit: V
        self.np_time = np.array(self.time) # Unit: s
        self.np_current = np.array(self.current) # Unit: A
        self.cumulative_charge = self._calculate_charge() if charge is None else charge # Unit: C
        self.mass_of_active_material = float(args.mass_of_active_material) if args.mass_of_active_material is not None else None # Unit: g
        self.area_of_active_material = float(args.area_of_active_material) if args.area_of_active_material is not None else 1 # Unit: cm^2
        self.concentration_of_active_material = float(args.concentration_of_active_material) if args.concentration_of_active_material is not None else 1 # Unit: mol/cm^3
        self.window_size = int(args.window_size) if args.window_size is not None else 10
        self.diffusion_coefficient = None # Unit: cm^2/s
        self.reaction_order = None # 1 or 2
        self.reaction_rate_constant = None # Unit: 1/s or cm^3/mol/s

    def analyze(self):
        # Calculate diffusion coefficient
        self._calculate_diffusion_coefficient()

        # Reaction kinetics analysis
        self.reaction_kinetics = self._analyze_reaction_kinetics()

        # Validate and preprocess data
        self._preprocess_data()


    def _calculate_charge(self):
        """ Calculate the cumulative charge passed in a chronoamperometry experiment."""
        # Calculate the time intervals (delta t)
        delta_t = np.diff(self.np_time)

        # Calculate the charge for each interval as the product of the interval duration and the current at the end of the interval
        interval_charges = delta_t * self.np_current[1:]

        # Compute the cumulative charge
        self.cumulative_charge = np.cumsum(np.insert(interval_charges, 0, 0)).tolist()


    def _calculate_diffusion_coefficient(self):
        """ Calculate the diffusion coefficient using Cottrell analysis."""
        log.info("Calculating diffusion coefficient using Cottrell analysis...")
        # Find the best linear region for Cottrell analysis
        t_inv_sqrt = np.sqrt(1 / self.np_time[1:])  # Avoid division by zero
        best_fit = self._analyze_best_linear_fit(t_inv_sqrt, self.np_current[1:])
        slope = best_fit['slope']
        # Constants for Cottrell equation
        faraday_constant = const.physical_constants["Faraday constant"][0]  # Faraday constant in C/mol
        # Calculate D using the slope
        # Unit of D: cm^2/s
        # Cortrell equation: I = (nFAD^1/2 * C)/ (pi^1/2 * t^1/2)
        self.diffusion_coefficient = (slope ** 2 * np.pi) / (self.number_of_electrons ** 2 * faraday_constant ** 2 * self.area_of_active_material ** 2 * self.concentration_of_active_material ** 2)
        log.info(f"Diffusion coefficient: {self.diffusion_coefficient} cm^2/s")


    def _analyze_reaction_kinetics(self):
        """
        Analyze the reaction kinetics to determine if the reaction is first or second order.
        for the first order, the rate low: ln(I) = ln(I0) - kt
        for the second order, the rate low: 1/I = 1/I0 + kt
        and calculate the rate constant accordingly.
        """
        # Analyze for first-order kinetics
        log.info("Analyzing reaction kinetics for first kinetic order...")
        first_order_fit = self._analyze_best_linear_fit(x_data=self.np_time[1:], y_data=np.log(self.np_current[1:]))
        # Analyze for second-order kinetics
        log.info("Analyzing reaction kinetics for second kinetic order...")
        second_order_fit = self._analyze_best_linear_fit( x_data=self.np_time[1:], y_data=1/self.np_current[1:])

        # Determine which order fits best
        if first_order_fit['r_squared'] > second_order_fit['r_squared']:
            self.reaction_order = 1
            # Assigning the negative of the slope for first-order kinetics
            self.reaction_rate_constant = -first_order_fit['slope']
            log.info(f"Reaction rate constant for first order: {self.reaction_rate_constant} 1/s")
            log.info("A positive rate constant indicates a decay process, while a negative one indicates an increasing process or growth.")

        else:
            self.reaction_order = 2
            self.reaction_rate_constant = second_order_fit['slope']
            log.info(f"Reaction rate constant for second order: {self.reaction_rate_constant} cm^3/mol/s")
            log.info("A positive rate constant indicates a typical second-order increasing concentration process.")


    def _analyze_best_linear_fit(self, x_data, y_data):
        """
        Find the best linear region for the provided data.

        Args:
            x_data (np.array): Transformed time array (e.g., t^(-1/2) for diffusion or time for kinetics).
            y_data (np.array): Current array or transformed current array (e.g., log(current)).

        Returns:
            best fit (dict): Dictionary containing the best linear fit parameters:
                start_index (int): Start index of the best linear region.
                end_index (int): End index of the best linear region.
                slope (float): Slope of the best linear fit.
                intercept (float): Intercept of the best linear fit.
                r_squared (float): R-squared value of the best linear fit.
        """

        best_fit = {'start': 0, 'end': self.window_size, 'r_squared': 0, 'slope': 0, 'intercept': 0}
        for start in range(len(x_data) - self.window_size + 1):
            end = start + self.window_size
            slope, intercept, r_value, _, _ = linregress(x_data[start:end], y_data[start:end])
            r_squared = r_value**2
            if r_squared > best_fit['r_squared']:
                best_fit.update({'start': start, 'end': end, 'r_squared': r_squared, 'slope': slope, 'intercept': intercept})
        log.info(f"Best linear fit found from {best_fit['start']} to {best_fit['end']} with R^2 = {best_fit['r_squared']}")
        return best_fit


    def _preprocess_data(self):
        # Data validation and preprocessing
        pass

    def plot(self):
        pass

    def save_data(self):
        pass

    def perform_all_actions(self, save_dir:str, plots:list, optional_name:str = None):
        self.analyze()
        self.plot(save_dir, plots, optional_name=optional_name)
        self.save_data(save_dir=save_dir, optional_name=optional_name)
