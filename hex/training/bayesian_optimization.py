import time
import json
import os
from configparser import ConfigParser
import skopt

from hex.training.repeated_self_training import RepeatedSelfTrainer, load_reference_models
from hex.utils.logger import logger


def parameter_dict_to_named_arg(pdict):
    bounds = pdict["bounds"]
    if all(isinstance(x, float) for x in bounds):
        prior = "log-uniform" if pdict.get("log_scale") else "uniform"
        return skopt.utils.Real(low=bounds[0], high=bounds[1], prior=prior, name=pdict["name"])
    elif all(isinstance(x, int) for x in bounds):
        return skopt.utils.Integer(low=bounds[0], high=bounds[1], name=pdict["name"])
    elif all(isinstance(x, str) for x in bounds):
        return skopt.utils.Categorical(categories=bounds, name=pdict["name"])
    else:
        logger.info(f"=== parameter {pdict['name']} doesn't match types ===")
        raise SystemExit

def bayesian_optimization():
    #runs Bayesian Optimization with given parameters and "loop_count" steps
    #optimizes by ELO value compared to starting and reference models

    parameters_path = "bo_parameters.json"
    if not os.path.isfile(parameters_path):
        with open(parameters_path, 'w') as file:
            file.write("[]")

    with open("bo_parameters.json") as file:
        parameters = json.load(file)

    if parameters == []:
        logger.info(f"parameter list in file {parameters_path} is empty")
        raise SystemExit

    config = ConfigParser()
    config.read('config.ini')
    reference_models = load_reference_models(config)
    space = [parameter_dict_to_named_arg(pdict) for pdict in parameters]

    @skopt.utils.use_named_args(space)
    def train_evaluate(**params):
        trainer = RepeatedSelfTrainer(config)
        trainer.reference_models = reference_models

        start_time = time.time()
        for parameter_name, value in params.items():
            section, convert = next((parameter["section"], parameter.get("convert_to_int", False))
                for parameter in parameters if parameter["name"] == parameter_name)
            value = int(value) if convert else value
            trainer.config[section][parameter_name] = str(value)
            logger.info(f"Bayesian Optimization {parameter_name}: {value}")

        trainer.prepare_rst()
        loop_idx = config.getint('REPEATED SELF TRAINING', 'start_index') + 1

        while True:
            if time.time() - start_time < config["BAYESIAN OPTIMIZATION"].getfloat("loop_time"):
                trainer.rst_loop(loop_idx)
                loop_idx += 1
            else:
                break

        return -trainer.get_best_rating()

    res_gp = skopt.gp_minimize(
        func=train_evaluate,
        dimensions=space,
        n_calls=config["BAYESIAN OPTIMIZATION"].getint("loop_count"),
        n_random_starts=config["BAYESIAN OPTIMIZATION"].getint("random_count"),
        noise=config["BAYESIAN OPTIMIZATION"].getfloat("noise")
        )

    skopt.dump(res_gp, f"bayes_experiments/{config['CREATE MODEL'].get('model_name')}.p",
        store_objective=False)

    logger.info("=== best parameters are ===")
    logger.info((res_gp.x, res_gp.fun))


if __name__ == '__main__':
    bayesian_optimization()
